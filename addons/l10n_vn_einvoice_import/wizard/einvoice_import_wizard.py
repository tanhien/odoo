# Part of Odoo. See LICENSE file for full copyright and licensing details.

import base64
import json
import logging
import re

import requests

from lxml import etree

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command

_logger = logging.getLogger(__name__)

# Default values (overridden by Settings > Accounting > E-Invoice Import)
DEFAULT_LLM_URL = 'http://192.168.1.185:1234/v1/chat/completions'
DEFAULT_LLM_MODEL = 'qwen/qwen3-vl-8b'
DEFAULT_LLM_TIMEOUT = 120


class L10nVnEinvoiceImportWizard(models.TransientModel):
    _name = 'l10n_vn_einvoice_import.wizard'
    _description = 'Vietnamese E-Invoice Import Wizard'

    file_data = fields.Binary(string='Invoice File', required=True, attachment=False)
    file_name = fields.Char(string='File Name')
    import_status = fields.Text(string='Import Status', readonly=True)
    created_move_id = fields.Many2one('account.move', string='Created Invoice', readonly=True)

    def action_import(self):
        """Main entry point: parse uploaded file and create invoice."""
        self.ensure_one()
        if not self.file_data:
            raise UserError(_('Please upload a file.'))

        raw = base64.b64decode(self.file_data)
        fname = (self.file_name or '').lower()

        if fname.endswith('.xml'):
            invoice_data = self._parse_xml(raw)
        elif fname.endswith('.pdf'):
            invoice_data = self._parse_pdf_via_llm(raw)
        else:
            raise UserError(_('Unsupported file format. Please upload an XML or PDF file.'))

        move = self._create_invoice(invoice_data)
        self._attach_file(move, raw)

        self.created_move_id = move.id
        self.import_status = _('Invoice %s created successfully.', move.ref or 'Draft')

        move_type = invoice_data.get('move_type', 'in_invoice')
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': move.id,
            'view_mode': 'form',
            'context': {'default_move_type': move_type},
        }

    # -------------------------------------------------------------------------
    # Invoice Direction Detection
    # -------------------------------------------------------------------------

    def _detect_move_type(self, seller_data, buyer_data):
        """Detect if this is a sales or purchase invoice.

        If seller MST matches our company → out_invoice (we are selling)
        If buyer MST matches our company → in_invoice (we are buying)
        Default: in_invoice
        """
        company_vat = (self.env.company.vat or '').strip()
        seller_vat = (seller_data.get('vat') or '').strip()
        buyer_vat = (buyer_data.get('vat') or '').strip()

        if company_vat and seller_vat and seller_vat == company_vat:
            return 'out_invoice'
        if company_vat and buyer_vat and buyer_vat == company_vat:
            return 'in_invoice'

        # Fallback: check context or default
        return self.env.context.get('default_move_type', 'in_invoice')

    # -------------------------------------------------------------------------
    # XML Parsing
    # -------------------------------------------------------------------------

    def _parse_xml(self, raw):
        """Parse Vietnamese e-invoice XML (TCT format) into a structured dict."""
        try:
            root = etree.fromstring(raw)
        except etree.XMLError as e:
            raise UserError(_('Invalid XML file: %s', str(e)))

        dlhdon = root.find('.//DLHDon')
        if dlhdon is None:
            raise UserError(_('Invalid XML: missing DLHDon element.'))

        ttchung = dlhdon.find('TTChung')
        ndhdon = dlhdon.find('NDHDon')
        if ndhdon is None:
            raise UserError(_('Invalid XML: missing NDHDon element.'))

        # Common info
        invoice_number = self._xml_text(ttchung, 'SHDon')
        invoice_series = self._xml_text(ttchung, 'KHHDon')
        invoice_template = self._xml_text(ttchung, 'KHMSHDon')
        invoice_date = self._xml_text(ttchung, 'NLap')
        currency_code = self._xml_text(ttchung, 'DVTTe') or 'VND'

        # Seller (NBan)
        nban = ndhdon.find('NBan')
        seller = {
            'name': self._xml_text(nban, 'Ten'),
            'vat': self._xml_text(nban, 'MST'),
            'address': self._xml_text(nban, 'DChi'),
            'phone': self._xml_text(nban, 'SDThoai'),
        }

        # Buyer (NMua) - may be a company (has Ten/MST) or individual (has HVTNMHang/CCCDan)
        nmua = ndhdon.find('NMua')
        buyer_name = self._xml_text(nmua, 'Ten') or self._xml_text(nmua, 'HVTNMHang')
        buyer_vat = self._xml_text(nmua, 'MST')
        buyer = {
            'name': buyer_name,
            'vat': buyer_vat,
            'address': self._xml_text(nmua, 'DChi'),
            'customer_code': self._xml_text(nmua, 'MKHang'),
            'phone': self._xml_text(nmua, 'SDThoai'),
            'cccd': self._xml_text(nmua, 'CCCDan'),
            'email': self._xml_text(nmua, 'DCTDTu'),
            'is_company': bool(buyer_vat),
        }

        # Line items - only TChat=1 (actual product/service lines)
        lines = []
        for hhd in ndhdon.findall('.//DSHHDVu/HHDVu'):
            tchat = self._xml_text(hhd, 'TChat')
            if tchat != '1':
                continue
            lines.append({
                'name': self._xml_text(hhd, 'THHDVu') or '',
                'uom': self._xml_text(hhd, 'DVTinh') or '',
                'quantity': self._xml_float(hhd, 'SLuong') or 1.0,
                'price_unit': self._xml_float(hhd, 'DGia') or 0.0,
                'tax_rate_str': self._xml_text(hhd, 'TSuat') or '',
                'subtotal': self._xml_float(hhd, 'ThTien') or 0.0,
            })

        # Totals
        ttoan = ndhdon.find('TToan')
        totals = {
            'untaxed': self._xml_float(ttoan, 'TgTCThue') or 0.0,
            'tax': self._xml_float(ttoan, 'TgTThue') or 0.0,
            'total': self._xml_float(ttoan, 'TgTTTBSo') or 0.0,
        }

        einvoice_ref = f"{invoice_template}{invoice_series}{invoice_number}"

        # Detect invoice direction
        move_type = self._detect_move_type(seller, buyer)

        return {
            'move_type': move_type,
            'invoice_number': invoice_number,
            'invoice_series': invoice_series,
            'invoice_template': invoice_template,
            'einvoice_ref': einvoice_ref,
            'invoice_date': invoice_date,
            'currency_code': currency_code,
            'seller': seller,
            'buyer': buyer,
            'lines': lines,
            'totals': totals,
        }

    def _xml_text(self, parent, tag):
        """Safe extraction of text from an XML element."""
        if parent is None:
            return ''
        elem = parent.find(tag)
        return (elem.text or '').strip() if elem is not None else ''

    def _xml_float(self, parent, tag):
        """Safe extraction of a float from an XML element."""
        text = self._xml_text(parent, tag)
        if not text:
            return 0.0
        try:
            return float(text)
        except ValueError:
            return 0.0

    # -------------------------------------------------------------------------
    # VND Amount Parsing
    # -------------------------------------------------------------------------

    @staticmethod
    def _parse_vnd_amount(value):
        """Parse a VND amount that may use dots as thousands separators.

        In Vietnamese formatting:
          196.000 = 196000
          178.182 = 178182
          17.818  = 17818
        VND has no decimal subdivision, so dots are always thousands separators.

        When json.loads parses "178.182", it becomes Python float 178.182.
        We detect this pattern (N.NNN = exactly 3 decimal digits) and fix it.
        """
        if not value:
            return 0.0
        if isinstance(value, (int, float)):
            # Detect mis-parsed VND: float with exactly 3 decimal digits
            # e.g. 178.182 should be 178182, 17.818 should be 17818
            text = str(float(value))
            m = re.match(r'^(\d+)\.(\d{3})$', text)
            if m:
                return float(m.group(1) + m.group(2))
            return float(value)
        # String value: remove dots (thousands sep) and commas, then parse
        text = str(value).strip().replace('.', '').replace(',', '')
        try:
            return float(text)
        except ValueError:
            return 0.0

    # -------------------------------------------------------------------------
    # PDF OCR via LLM
    # -------------------------------------------------------------------------

    def _get_llm_config(self):
        """Read LLM configuration from system parameters."""
        ICP = self.env['ir.config_parameter'].sudo()
        return {
            'url': ICP.get_param('l10n_vn_einvoice_import.llm_url', DEFAULT_LLM_URL),
            'model': ICP.get_param('l10n_vn_einvoice_import.llm_model', DEFAULT_LLM_MODEL),
            'timeout': int(ICP.get_param('l10n_vn_einvoice_import.llm_timeout', DEFAULT_LLM_TIMEOUT)),
        }

    def _parse_pdf_via_llm(self, raw):
        """Convert PDF to images and use LLM vision API for OCR extraction."""
        llm_config = self._get_llm_config()

        images_b64 = self._pdf_to_images_b64(raw)
        if not images_b64:
            raise UserError(_('Could not extract images from the PDF file.'))

        prompt = (
            "Analyze this Vietnamese e-invoice (hoa don dien tu) image and extract information.\n"
            "IMPORTANT: All monetary amounts must be integers WITHOUT dots or commas.\n"
            "In Vietnamese currency (VND), 196.000 means 196000, 44.010 means 44010.\n"
            "The buyer may be a company (has MST/tax code) or an individual (has CCCD/ID number).\n"
            "If the buyer has no MST, set buyer.vat to empty string and fill buyer.cccd with their ID number.\n"
            "Return ONLY a JSON object with this exact structure, no other text:\n"
            "{\n"
            '  "invoice_number": "invoice number (So hoa don)",\n'
            '  "invoice_series": "invoice series (Ky hieu)",\n'
            '  "invoice_template": "template code",\n'
            '  "invoice_date": "YYYY-MM-DD",\n'
            '  "currency_code": "VND",\n'
            '  "seller": {"name": "seller name", "vat": "seller MST", "address": "seller address"},\n'
            '  "buyer": {"name": "buyer name", "vat": "buyer MST or empty", '
            '"address": "buyer address", "cccd": "buyer CCCD/ID or empty"},\n'
            '  "lines": [{"name": "description", "uom": "unit", "quantity": 1, '
            '"price_unit": 44010, "tax_rate_str": "10% or KCT", "subtotal": 44010}],\n'
            '  "totals": {"untaxed": 44604, "tax": 0, "total": 44604}\n'
            "}\n"
        )

        content = [{"type": "text", "text": prompt}]
        for img_b64 in images_b64[:3]:
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"},
            })

        try:
            response = requests.post(
                llm_config['url'],
                json={
                    'model': llm_config['model'],
                    'messages': [{'role': 'user', 'content': content}],
                    'temperature': 0.1,
                    'max_tokens': 4096,
                },
                timeout=llm_config['timeout'],
            )
            response.raise_for_status()
            result = response.json()
            text = result['choices'][0]['message']['content']
        except requests.RequestException as e:
            raise UserError(_('Error contacting LLM OCR API: %s', str(e)))
        except (KeyError, IndexError) as e:
            raise UserError(_('Unexpected LLM API response format: %s', str(e)))

        # Strip Qwen3 <think>...</think> tags if present
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()

        # Extract JSON from response (handle markdown code blocks)
        if '```json' in text:
            text = text.split('```json')[1].split('```')[0]
        elif '```' in text:
            text = text.split('```')[1].split('```')[0]

        # Last resort: find first { ... } block
        text = text.strip()
        if not text.startswith('{'):
            start = text.find('{')
            end = text.rfind('}')
            if start != -1 and end != -1:
                text = text[start:end + 1]

        # Fix VND thousands separators BEFORE json.loads.
        # "196.000" (VND) would be parsed as 196.0 by JSON.
        # Pattern: number like 196.000 or 1.234.567 (dots followed by exactly 3 digits)
        text = re.sub(
            r'(?<=[:\s,\[])(\d{1,3}(?:\.\d{3})+)(?=[,\s\}\]\n])',
            lambda m: m.group(1).replace('.', ''),
            text,
        )

        try:
            invoice_data = json.loads(text.strip())
        except json.JSONDecodeError as e:
            raise UserError(_('Could not parse LLM response as JSON: %s\n\nRaw response:\n%s', str(e), text))

        # Build einvoice_ref
        tmpl = invoice_data.get('invoice_template', '')
        series = invoice_data.get('invoice_series', '')
        num = invoice_data.get('invoice_number', '')
        invoice_data['einvoice_ref'] = f"{tmpl}{series}{num}"

        # Ensure lines have proper numeric types (handle VND thousands separator)
        for line in invoice_data.get('lines', []):
            line['quantity'] = float(line.get('quantity', 1) or 1)
            line['price_unit'] = self._parse_vnd_amount(line.get('price_unit', 0))
            line['subtotal'] = self._parse_vnd_amount(line.get('subtotal', 0))
        totals = invoice_data.get('totals', {})
        totals['untaxed'] = self._parse_vnd_amount(totals.get('untaxed', 0))
        totals['tax'] = self._parse_vnd_amount(totals.get('tax', 0))
        totals['total'] = self._parse_vnd_amount(totals.get('total', 0))

        # Detect direction
        seller = invoice_data.get('seller', {})
        buyer = invoice_data.get('buyer', {})
        buyer.setdefault('is_company', bool(buyer.get('vat')))
        invoice_data['move_type'] = self._detect_move_type(seller, buyer)

        return invoice_data

    def _pdf_to_images_b64(self, raw):
        """Convert PDF bytes to list of base64-encoded JPEG images."""
        images_b64 = []
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(stream=raw, filetype='pdf')
            for page_num in range(min(len(doc), 3)):
                page = doc[page_num]
                mat = fitz.Matrix(150 / 72, 150 / 72)  # 150 DPI
                pix = page.get_pixmap(matrix=mat)
                img_bytes = pix.tobytes('jpeg')
                images_b64.append(base64.b64encode(img_bytes).decode('ascii'))
            doc.close()
        except ImportError:
            try:
                import io
                from pdf2image import convert_from_bytes
                images = convert_from_bytes(raw, dpi=150, last_page=3)
                for img in images:
                    buf = io.BytesIO()
                    img.save(buf, format='JPEG', quality=80)
                    images_b64.append(base64.b64encode(buf.getvalue()).decode('ascii'))
            except ImportError:
                raise UserError(_(
                    'PDF processing requires PyMuPDF or pdf2image. '
                    'Install with: pip install PyMuPDF'
                ))
        return images_b64

    # -------------------------------------------------------------------------
    # Partner & Tax Resolution
    # -------------------------------------------------------------------------

    def _resolve_partner(self, party_data, is_customer=False):
        """Find or create a partner from invoice party data.

        Handles both companies (identified by MST/vat) and individuals
        (identified by CCCD or name).

        Args:
            party_data: dict with keys: name, vat, address, cccd, email, is_company
            is_customer: if True, set customer_rank; if False, set supplier_rank
        """
        Partner = self.env['res.partner']
        vat = (party_data.get('vat') or '').strip()
        name = (party_data.get('name') or '').strip()
        address = party_data.get('address', '')
        cccd = (party_data.get('cccd') or '').strip()
        email = (party_data.get('email') or '').strip()
        is_company = party_data.get('is_company', bool(vat))

        if not vat and not name and not cccd:
            raise UserError(_('Cannot identify partner: no tax code, name, or ID found.'))

        # Search order: VAT (MST) → CCCD (ref) → name
        partner = Partner.browse()
        if vat:
            partner = Partner.search([('vat', '=', vat)], limit=1)
        if not partner and cccd:
            partner = Partner.search([('ref', '=', cccd)], limit=1)
        if not partner and name:
            partner = Partner.search([('name', '=', name)], limit=1)

        if not partner:
            partner_vals = {
                'name': name or vat or cccd,
                'company_type': 'company' if is_company else 'person',
            }
            if is_customer:
                partner_vals['customer_rank'] = 1
            else:
                partner_vals['supplier_rank'] = 1
            if vat:
                partner_vals['vat'] = vat
            if cccd:
                partner_vals['ref'] = cccd
            if address:
                partner_vals['street'] = address
            if email:
                partner_vals['email'] = email
            partner = Partner.create(partner_vals)
            _logger.info(
                'Created new partner: %s (MST: %s, CCCD: %s)',
                partner.name, vat or '-', cccd or '-',
            )

        return partner

    def _resolve_tax(self, tax_rate_str, tax_use='purchase'):
        """Map a tax rate string (e.g. '10%', 'KCT') to an account.tax record.

        Args:
            tax_rate_str: tax rate from invoice (e.g. '10%', '5%', 'KCT')
            tax_use: 'purchase' for vendor bills, 'sale' for customer invoices
        """
        Tax = self.env['account.tax']
        rate_str = (tax_rate_str or '').strip().replace('%', '').strip()

        if rate_str.upper() in ('KCT', 'KKKNT', ''):
            return Tax.search([
                ('type_tax_use', '=', tax_use),
                ('amount', '=', 0),
                ('company_id', '=', self.env.company.id),
            ], limit=1)

        try:
            rate = float(rate_str)
        except ValueError:
            return Tax.browse()

        return Tax.search([
            ('type_tax_use', '=', tax_use),
            ('amount', '=', rate),
            ('amount_type', '=', 'percent'),
            ('company_id', '=', self.env.company.id),
        ], limit=1)

    # -------------------------------------------------------------------------
    # Invoice Creation
    # -------------------------------------------------------------------------

    def _create_invoice(self, invoice_data):
        """Create an account.move from parsed invoice data.

        Automatically detects direction:
        - out_invoice: seller is our company → partner = buyer (customer)
        - in_invoice: buyer is our company → partner = seller (vendor)
        """
        move_type = invoice_data.get('move_type', 'in_invoice')
        is_sale = move_type == 'out_invoice'

        # Resolve partner: for sales → buyer is the partner; for purchases → seller
        if is_sale:
            partner = self._resolve_partner(
                invoice_data.get('buyer', {}), is_customer=True,
            )
            tax_use = 'sale'
        else:
            partner = self._resolve_partner(
                invoice_data.get('seller', {}), is_customer=False,
            )
            tax_use = 'purchase'

        # Parse invoice date
        invoice_date = invoice_data.get('invoice_date')
        if invoice_date and isinstance(invoice_date, str):
            try:
                invoice_date = fields.Date.to_date(invoice_date)
            except (ValueError, TypeError):
                invoice_date = fields.Date.today()
        else:
            invoice_date = fields.Date.today()

        # Resolve currency
        currency = self.env['res.currency'].search(
            [('name', '=', invoice_data.get('currency_code', 'VND'))],
            limit=1,
        )

        # Build invoice lines
        invoice_line_ids = []
        for line_data in invoice_data.get('lines', []):
            tax = self._resolve_tax(line_data.get('tax_rate_str', ''), tax_use)
            line_vals = {
                'name': line_data.get('name') or _('Imported line'),
                'quantity': line_data.get('quantity', 1.0),
                'price_unit': line_data.get('price_unit', 0.0),
            }
            if tax:
                line_vals['tax_ids'] = [Command.set(tax.ids)]
            invoice_line_ids.append(Command.create(line_vals))

        if not invoice_line_ids:
            invoice_line_ids = [Command.create({
                'name': _('E-Invoice Import'),
                'quantity': 1,
                'price_unit': invoice_data.get('totals', {}).get('untaxed', 0),
            })]

        einvoice_ref = invoice_data.get('einvoice_ref', '')

        move_vals = {
            'move_type': move_type,
            'partner_id': partner.id,
            'invoice_date': invoice_date,
            'ref': einvoice_ref,
            'l10n_vn_e_invoice_number': einvoice_ref,
            'invoice_line_ids': invoice_line_ids,
        }
        if currency:
            move_vals['currency_id'] = currency.id

        move = self.env['account.move'].create(move_vals)
        label = 'customer invoice' if is_sale else 'vendor bill'
        _logger.info('Created %s: %s (ref: %s)', label, move.name, einvoice_ref)
        return move

    def _attach_file(self, move, raw):
        """Attach the original imported file to the created invoice."""
        fname = self.file_name or 'einvoice_import'
        mimetype = 'application/xml' if fname.lower().endswith('.xml') else 'application/pdf'
        self.env['ir.attachment'].create({
            'name': fname,
            'type': 'binary',
            'datas': base64.b64encode(raw),
            'res_model': 'account.move',
            'res_id': move.id,
            'mimetype': mimetype,
        })
