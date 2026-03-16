# Part of Odoo. See LICENSE file for full copyright and licensing details.

import base64
import datetime
import hashlib
import json
import logging
import re

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Scoring weights for matching
SCORE_AMOUNT = 50
SCORE_DATE_SAME = 30
SCORE_DATE_3D = 25
SCORE_DATE_7D = 15
SCORE_DATE_30D = 5
SCORE_INVOICE_REF = 40
SCORE_PARTNER_NAME = 20
SCORE_PARTNER_REF = 15
SCORE_SO_PO = 20
MIN_SUGGEST_SCORE = 50

INVOICE_PATTERNS = [
    r'\b(?:HD|HĐ|INV|SO|PO)[-:\s]?(\d{4,10})\b',
    r'\b(\d{5,10})\b',
]

FEE_KEYWORDS = [
    'PHI NGAN HANG', 'PHI NH', 'PHI CK', 'PHI CHUYEN KHOAN',
    'PHI GIAO DICH', 'FEE', 'SERVICE CHARGE', 'PHI DV',
]

DEFAULT_LLM_URL = 'http://192.168.1.185:1234/v1/chat/completions'
DEFAULT_LLM_MODEL = 'qwen/qwen3-vl-8b'
DEFAULT_LLM_TIMEOUT = 120


class ImportWizardLine(models.TransientModel):
    _name = 'l10n_vn_bank_statement_import.wizard.line'
    _description = 'Import Preview Line'

    wizard_id = fields.Many2one(
        'l10n_vn_bank_statement_import.wizard', required=True, ondelete='cascade',
    )
    date = fields.Date(string='Date')
    amount = fields.Float(string='Amount')
    payment_ref = fields.Char(string='Description')
    txn_ref = fields.Char(string='Txn Ref')
    line_type = fields.Selection([
        ('payment', 'Payment'),
        ('fee', 'Bank Fee'),
        ('skip', 'Skip'),
    ], default='payment', required=True, string='Type')
    suggested_bill_id = fields.Many2one(
        'account.move', string='Matched Bill/Invoice',
        domain="[('id', 'in', available_bill_ids)]",
    )
    available_bill_ids = fields.Many2many(
        'account.move', compute='_compute_available_bills',
    )
    match_score = fields.Integer(string='Score', readonly=True)

    @api.depends('amount', 'wizard_id.journal_id')
    def _compute_available_bills(self):
        for line in self:
            if not line.wizard_id.journal_id:
                line.available_bill_ids = False
                continue
            company = line.wizard_id.journal_id.company_id
            if line.amount < 0:
                move_types = ('in_invoice', 'out_refund')
            else:
                move_types = ('out_invoice', 'in_refund')
            line.available_bill_ids = self.env['account.move'].sudo().search([
                ('move_type', 'in', move_types),
                ('payment_state', 'in', ('not_paid', 'partial')),
                ('state', '=', 'posted'),
                ('company_id', '=', company.id),
            ])


class L10nVnBankStatementImportWizard(models.TransientModel):
    _name = 'l10n_vn_bank_statement_import.wizard'
    _description = 'Vietnamese Bank Statement Import Wizard'

    state = fields.Selection([
        ('upload', 'Upload'),
        ('preview', 'Preview'),
    ], default='upload', readonly=True)
    file_data = fields.Binary(string='Statement File', attachment=False)
    file_name = fields.Char(string='File Name')
    journal_id = fields.Many2one(
        'account.journal', string='Bank Journal',
        required=True, domain="[('type', '=', 'bank')]",
    )
    match_tolerance_amount = fields.Float(
        string='Match Tolerance (VND)', default=2000.0,
        help='Maximum amount difference for matching.',
    )
    preview_line_ids = fields.One2many(
        'l10n_vn_bank_statement_import.wizard.line', 'wizard_id',
        string='Transactions',
    )
    import_status = fields.Text(string='Status', readonly=True)

    # -------------------------------------------------------------------------
    # Step 1: Parse & Match
    # -------------------------------------------------------------------------

    def action_parse(self):
        """Parse file, run matching engine, show preview."""
        self.ensure_one()
        if not self.file_data:
            raise UserError(_('Please upload a file.'))

        raw = base64.b64decode(self.file_data)
        fname = (self.file_name or '').lower()

        if fname.endswith('.xls') or fname.endswith('.xlsx'):
            parsed_data = self._parse_xls(raw)
        elif fname.endswith('.pdf'):
            parsed_data = self._parse_pdf_via_llm(raw)
        else:
            raise UserError(_('Unsupported file format. Please upload an XLS or PDF file.'))

        transactions = parsed_data.get('transactions', [])
        if not transactions:
            raise UserError(_('No transactions found in the file.'))

        clean_txns, dupe_count = self._check_duplicates(transactions)
        if not clean_txns:
            raise UserError(_('All %d transactions already exist (duplicates).', dupe_count))

        # Get open bills for matching
        company = self.journal_id.company_id
        open_bills = self.env['account.move'].sudo().search([
            ('move_type', 'in', ('in_invoice', 'out_refund', 'out_invoice', 'in_refund')),
            ('payment_state', 'in', ('not_paid', 'partial')),
            ('state', '=', 'posted'),
            ('company_id', '=', company.id),
        ])

        # Build preview lines with suggestions
        line_vals = []
        for txn in clean_txns:
            ref_upper = (txn.get('payment_ref', '') or '').upper()
            is_fee = self._is_bank_fee(ref_upper)

            suggested_bill = False
            score = 0
            if not is_fee:
                suggested_bill, score = self._find_best_match(
                    txn, open_bills, self.match_tolerance_amount,
                )

            line_vals.append((0, 0, {
                'date': txn['date'],
                'amount': txn['amount'],
                'payment_ref': txn.get('payment_ref', ''),
                'txn_ref': txn.get('ref', ''),
                'line_type': 'fee' if is_fee else 'payment',
                'suggested_bill_id': suggested_bill.id if suggested_bill else False,
                'match_score': score,
            }))

        self.write({
            'state': 'preview',
            'preview_line_ids': line_vals,
            'import_status': _('%d transactions parsed (%d duplicates skipped).', len(clean_txns), dupe_count),
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # -------------------------------------------------------------------------
    # Step 2: Create Payments
    # -------------------------------------------------------------------------

    def action_confirm(self):
        """Create payments from confirmed preview lines."""
        self.ensure_one()
        lines = self.preview_line_ids.filtered(lambda l: l.line_type != 'skip')
        if not lines:
            raise UserError(_('No transactions to import (all skipped).'))

        ICP = self.env['ir.config_parameter'].sudo()
        fee_account_code = ICP.get_param(
            'l10n_vn_bank_statement_import.fee_account_code', '6427',
        )
        fee_account = self.env['account.account'].sudo().search([
            ('code', '=', fee_account_code),
            ('company_ids', 'in', self.journal_id.company_id.id),
        ], limit=1)

        created_payments = self.env['account.payment']
        results = {'matched': 0, 'fees': 0, 'unmatched': 0}

        for line in lines:
            if line.line_type == 'fee':
                payment = self._create_fee_payment(line, fee_account)
                if payment:
                    created_payments |= payment
                    results['fees'] += 1
                continue

            payment = self._create_payment(line)
            if not payment:
                continue
            created_payments |= payment

            if line.suggested_bill_id:
                if self._reconcile_payment_with_bill(payment, line.suggested_bill_id):
                    results['matched'] += 1
                else:
                    results['unmatched'] += 1
            else:
                results['unmatched'] += 1

        msg = _(
            'Created %d payments: %d matched with bills, %d fees, %d unmatched.',
            len(created_payments), results['matched'], results['fees'], results['unmatched'],
        )
        _logger.info(msg)

        if not created_payments:
            raise UserError(_('No payments were created.'))

        # Force paid state — transactions come from actual bank statements.
        # Use SQL to bypass _compute_state which resets reconciled payments
        # to 'in_process' (liquidity lines are not matched with bank statements).
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE account_payment SET state = 'paid' WHERE id IN %s",
            [tuple(created_payments.ids)],
        )
        created_payments.invalidate_recordset(['state'])

        action = {
            'type': 'ir.actions.act_window',
            'name': _('Imported Payments'),
            'res_model': 'account.payment',
            'context': {'create': False},
        }
        if len(created_payments) == 1:
            action.update({'view_mode': 'form', 'res_id': created_payments.id})
        else:
            action.update({
                'view_mode': 'list,form',
                'domain': [('id', 'in', created_payments.ids)],
            })
        return action

    def _create_payment(self, line):
        """Create an account.payment from a preview line."""
        vals = {
            'payment_type': 'outbound' if line.amount < 0 else 'inbound',
            'partner_type': 'supplier' if line.amount < 0 else 'customer',
            'amount': abs(line.amount),
            'date': line.date,
            'journal_id': self.journal_id.id,
            'memo': line.payment_ref or '',
            'payment_reference': line.txn_ref or '',
        }
        if line.suggested_bill_id:
            vals['partner_id'] = line.suggested_bill_id.partner_id.id

        try:
            payment = self.env['account.payment'].sudo().create(vals)
            payment.action_post()
            return payment
        except Exception as e:
            _logger.warning('Failed to create payment for "%s": %s', line.payment_ref, str(e))
            return False

    def _create_fee_payment(self, line, fee_account):
        """Create a payment for a bank fee transaction."""
        if not fee_account:
            _logger.warning('Fee account not found, skipping fee: %s', line.payment_ref)
            return False

        vals = {
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'amount': abs(line.amount),
            'date': line.date,
            'journal_id': self.journal_id.id,
            'memo': line.payment_ref or '',
            'payment_reference': line.txn_ref or '',
            'destination_account_id': fee_account.id,
        }
        try:
            payment = self.env['account.payment'].sudo().create(vals)
            payment.action_post()
            return payment
        except Exception as e:
            _logger.warning('Failed to create fee payment for "%s": %s', line.payment_ref, str(e))
            return False

    def _reconcile_payment_with_bill(self, payment, bill):
        """Reconcile a posted payment with a bill."""
        _liquidity, counterpart, _writeoff = payment._seek_for_lines()
        if not counterpart:
            _logger.warning('No counterpart line on payment %s', payment.name)
            return False

        bill_lines = bill.line_ids.filtered(
            lambda l: l.account_id.account_type in ('asset_receivable', 'liability_payable')
                      and not l.reconciled
        )
        if not bill_lines:
            _logger.warning('No unreconciled payable/receivable line on %s', bill.name)
            return False

        try:
            (counterpart + bill_lines[:1]).reconcile()
            _logger.info('Reconciled payment %s with %s', payment.name, bill.name)
            return True
        except Exception as e:
            _logger.warning('Failed to reconcile payment %s with %s: %s', payment.name, bill.name, str(e))
            return False

    # -------------------------------------------------------------------------
    # Enhanced Matching Engine (with date proximity)
    # -------------------------------------------------------------------------

    def _find_best_match(self, txn, open_bills, tolerance):
        """Find the best matching bill for a transaction. Returns (bill, score)."""
        amount = abs(txn['amount'])
        txn_date = txn['date']
        ref_upper = (txn.get('payment_ref', '') or '').upper()

        if txn['amount'] < 0:
            direction_types = ('in_invoice', 'out_refund')
        else:
            direction_types = ('out_invoice', 'in_refund')

        candidates = open_bills.filtered(lambda b: b.move_type in direction_types)
        if not candidates:
            return False, 0

        extracted_refs = self._extract_invoice_numbers(ref_upper)
        best_bill = False
        best_score = 0

        for bill in candidates:
            score = 0

            # 1. Amount match (+50)
            residual = abs(bill.amount_residual)
            if abs(residual - amount) <= tolerance:
                score += SCORE_AMOUNT

            # 2. Date proximity
            if isinstance(txn_date, datetime.date) and bill.invoice_date:
                delta = abs((txn_date - bill.invoice_date).days)
                if delta == 0:
                    score += SCORE_DATE_SAME
                elif delta <= 3:
                    score += SCORE_DATE_3D
                elif delta <= 7:
                    score += SCORE_DATE_7D
                elif delta <= 30:
                    score += SCORE_DATE_30D

            # 3. Invoice/bill reference in description (+40)
            inv_name = (bill.name or '').upper()
            inv_ref = (bill.ref or '').upper()
            einvoice_num = ''
            if hasattr(bill, 'l10n_vn_e_invoice_number'):
                einvoice_num = (bill.l10n_vn_e_invoice_number or '').upper()

            ref_matched = False
            for ref in extracted_refs:
                if ref in inv_name or ref in inv_ref or ref in einvoice_num:
                    score += SCORE_INVOICE_REF
                    ref_matched = True
                    break
            if not ref_matched and inv_ref and len(inv_ref) >= 5 and inv_ref in ref_upper:
                score += SCORE_INVOICE_REF

            # 4. Partner name in description (+20)
            if self._fuzzy_partner_match(ref_upper, bill.partner_id):
                score += SCORE_PARTNER_NAME

            # 5. SO/PO match (+20)
            if self._check_so_po_match(ref_upper, bill):
                score += SCORE_SO_PO

            if score > best_score:
                best_score = score
                best_bill = bill

        if best_score >= MIN_SUGGEST_SCORE:
            return best_bill, best_score
        return False, 0

    @staticmethod
    def _is_bank_fee(payment_ref):
        ref_upper = (payment_ref or '').upper()
        return any(kw in ref_upper for kw in FEE_KEYWORDS)

    @staticmethod
    def _extract_invoice_numbers(text):
        found = set()
        for pattern in INVOICE_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                found.add(match.group(match.lastindex or 0))
        return list(found)

    @staticmethod
    def _fuzzy_partner_match(payment_ref, partner):
        if not partner:
            return False
        partner_name = (partner.name or '').upper()
        if len(partner_name) >= 4 and partner_name in payment_ref:
            return True
        partner_ref = (partner.ref or '').upper()
        if partner_ref and len(partner_ref) >= 3 and partner_ref in payment_ref:
            return True
        return False

    @staticmethod
    def _check_so_po_match(payment_ref, invoice):
        origin = (invoice.invoice_origin or '').upper()
        if not origin:
            return False
        so_matches = re.findall(r'(S\d{4,10}|SO\d{4,10}|PO\d{4,10})', payment_ref)
        return any(so in origin for so in so_matches)

    # -------------------------------------------------------------------------
    # Duplicate Detection (checks existing payments)
    # -------------------------------------------------------------------------

    def _check_duplicates(self, transactions):
        """Filter out duplicate transactions by checking existing payments."""
        existing_payments = self.env['account.payment'].sudo().search([
            ('journal_id', '=', self.journal_id.id),
        ])

        existing_hashes = set()
        for p in existing_payments:
            h = self._txn_hash(str(p.date), p.amount_signed, p.memo)
            existing_hashes.add(h)

        clean = []
        dupes = 0
        for txn in transactions:
            h = self._txn_hash(str(txn['date']), txn['amount'], txn.get('payment_ref', ''))
            if h in existing_hashes:
                dupes += 1
            else:
                clean.append(txn)
                existing_hashes.add(h)
        return clean, dupes

    @staticmethod
    def _txn_hash(date_str, amount, payment_ref):
        key = f"{date_str}|{amount:.2f}|{(payment_ref or '').strip().upper()}"
        return hashlib.md5(key.encode('utf-8')).hexdigest()

    # -------------------------------------------------------------------------
    # XLS Parsing (Sacombank format) — KEPT AS-IS
    # -------------------------------------------------------------------------

    def _parse_xls(self, raw):
        """Parse Sacombank XLS bank statement into structured data."""
        try:
            import xlrd
        except ImportError:
            raise UserError(_('xlrd library is required. Install with: pip install xlrd'))

        try:
            book = xlrd.open_workbook(file_contents=raw)
        except Exception as e:
            raise UserError(_('Cannot open XLS file: %s', str(e)))

        sheet = book.sheet_by_index(0)

        account_number = ''
        balance_start = 0.0
        balance_end = 0.0

        for row_idx in range(min(11, sheet.nrows)):
            row_values = [sheet.cell_value(row_idx, col) for col in range(sheet.ncols)]
            row_text = ' '.join(str(v) for v in row_values)
            row_lower = row_text.lower()

            if 'tài khoản' in row_lower or 'tai khoan' in row_lower:
                for v in row_values:
                    v_str = str(v).strip()
                    acct_match = re.match(r'^(\d{10,15})$', v_str)
                    if acct_match:
                        account_number = acct_match.group(1)
                        break

            if 'dư đầu' in row_lower or 'du dau' in row_lower or 'đầu kỳ' in row_lower:
                for v in row_values:
                    parsed = self._parse_vnd_text(v)
                    if parsed > 0:
                        balance_start = parsed
                        break

            if 'dư cuối' in row_lower or 'du cuoi' in row_lower or 'cuối kỳ' in row_lower:
                for v in row_values:
                    parsed = self._parse_vnd_text(v)
                    if parsed > 0:
                        balance_end = parsed
                        break

        header_row = 11
        for row_idx in range(min(15, sheet.nrows)):
            cell_val = str(sheet.cell_value(row_idx, 0)).strip().upper()
            if cell_val == 'STT':
                header_row = row_idx
                break

        COL_STT = 0
        COL_TXN_REF = 1
        COL_TXN_DATE = 3
        COL_DESCRIPTION = 7
        COL_WITHDRAWAL = 9
        COL_DEPOSIT = 11

        transactions = []
        for row_idx in range(header_row + 1, sheet.nrows):
            stt_val = str(sheet.cell_value(row_idx, COL_STT)).strip()
            if not stt_val:
                continue
            try:
                int(float(stt_val))
            except (ValueError, TypeError):
                continue

            txn_date = self._parse_xls_date(sheet.cell(row_idx, COL_TXN_DATE), book)
            description = str(sheet.cell_value(row_idx, COL_DESCRIPTION) or '').strip()
            txn_ref = str(sheet.cell_value(row_idx, COL_TXN_REF) or '').strip()
            if txn_ref.endswith('.0'):
                txn_ref = txn_ref[:-2]

            withdrawal = self._parse_cell_amount(sheet.cell(row_idx, COL_WITHDRAWAL))
            deposit = self._parse_cell_amount(sheet.cell(row_idx, COL_DEPOSIT))
            amount = deposit - withdrawal

            if amount == 0.0 and not description:
                continue

            transactions.append({
                'date': txn_date,
                'ref': txn_ref,
                'payment_ref': description,
                'amount': amount,
            })

        return {
            'account_number': account_number,
            'balance_start': balance_start,
            'balance_end': balance_end,
            'transactions': transactions,
        }

    def _parse_xls_date(self, cell, book):
        import xlrd

        if cell.ctype in (xlrd.XL_CELL_DATE, xlrd.XL_CELL_NUMBER):
            try:
                dt_tuple = xlrd.xldate_as_tuple(cell.value, book.datemode)
                return datetime.date(dt_tuple[0], dt_tuple[1], dt_tuple[2])
            except (ValueError, xlrd.xldate.XLDateError):
                pass

        if cell.ctype == xlrd.XL_CELL_TEXT:
            text = cell.value.strip()
            if ' ' in text:
                text = text.split(' ')[0]
            for fmt in ('%d/%m/%Y', '%d-%m-%Y', '%Y-%m-%d', '%d.%m.%Y'):
                try:
                    return datetime.datetime.strptime(text, fmt).date()
                except ValueError:
                    continue

        return fields.Date.today()

    @staticmethod
    def _parse_vnd_text(value):
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
        text = str(value).strip()
        if re.match(r'^\d{1,3}(\.\d{3})+$', text):
            return float(text.replace('.', ''))
        return 0.0

    def _parse_cell_amount(self, cell):
        import xlrd

        if cell.ctype == xlrd.XL_CELL_EMPTY:
            return 0.0
        if cell.ctype == xlrd.XL_CELL_NUMBER:
            return self._parse_vnd_amount(cell.value)
        if cell.ctype == xlrd.XL_CELL_TEXT:
            text = cell.value.strip()
            if not text:
                return 0.0
            clean = text.replace('.', '').replace(',', '')
            try:
                return float(clean)
            except ValueError:
                return 0.0
        return 0.0

    @staticmethod
    def _parse_vnd_amount(value):
        if not value:
            return 0.0
        if isinstance(value, (int, float)):
            text = str(float(value))
            m = re.match(r'^(\d+)\.(\d{3})$', text)
            if m:
                return float(m.group(1) + m.group(2))
            return float(value)
        text = str(value).strip().replace('.', '').replace(',', '')
        try:
            return float(text)
        except ValueError:
            return 0.0

    # -------------------------------------------------------------------------
    # PDF Parsing via LLM — KEPT AS-IS
    # -------------------------------------------------------------------------

    def _parse_pdf_via_llm(self, raw):
        ICP = self.env['ir.config_parameter'].sudo()
        llm_config = {
            'url': ICP.get_param('l10n_vn_einvoice_import.llm_url', DEFAULT_LLM_URL),
            'model': ICP.get_param('l10n_vn_einvoice_import.llm_model', DEFAULT_LLM_MODEL),
            'timeout': int(ICP.get_param('l10n_vn_einvoice_import.llm_timeout', DEFAULT_LLM_TIMEOUT)),
        }

        einvoice_wiz = self.env['l10n_vn_einvoice_import.wizard']
        images_b64 = einvoice_wiz._pdf_to_images_b64(raw)
        if not images_b64:
            raise UserError(_('Could not extract images from the PDF file.'))

        prompt = (
            "Analyze this Vietnamese bank statement (sao ke ngan hang) image.\n"
            "Extract ALL transaction rows from the statement.\n"
            "Return ONLY a JSON object with this structure, no other text:\n"
            "{\n"
            '  "account_number": "bank account number",\n'
            '  "balance_start": 1234567,\n'
            '  "balance_end": 2345678,\n'
            '  "transactions": [\n'
            '    {\n'
            '      "date": "YYYY-MM-DD",\n'
            '      "ref": "transaction reference number",\n'
            '      "payment_ref": "description/content text",\n'
            '      "amount": 196000\n'
            '    }\n'
            '  ]\n'
            "}\n"
            "IMPORTANT RULES:\n"
            "- All amounts must be INTEGERS (no dots, no commas). In VND: 196.000 = 196000\n"
            "- Withdrawals (So tien rut) are NEGATIVE numbers\n"
            "- Deposits (So tien gui) are POSITIVE numbers\n"
            "- Dates must be in YYYY-MM-DD format\n"
            "- Extract EVERY transaction row, do not skip any\n"
        )

        content = [{"type": "text", "text": prompt}]
        for img_b64 in images_b64:
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
                    'max_tokens': 8192,
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

        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()

        if '```json' in text:
            text = text.split('```json')[1].split('```')[0]
        elif '```' in text:
            text = text.split('```')[1].split('```')[0]

        text = text.strip()
        if not text.startswith('{'):
            start = text.find('{')
            end = text.rfind('}')
            if start != -1 and end != -1:
                text = text[start:end + 1]

        text = re.sub(
            r'(?<=[:\s,\[])(\d{1,3}(?:\.\d{3})+)(?=[,\s\}\]\n])',
            lambda m: m.group(1).replace('.', ''),
            text,
        )

        try:
            parsed_data = json.loads(text.strip())
        except json.JSONDecodeError as e:
            raise UserError(_('Could not parse LLM response as JSON: %s\n\nRaw:\n%s', str(e), text))

        for txn in parsed_data.get('transactions', []):
            txn['amount'] = self._parse_vnd_amount(txn.get('amount', 0))
            date_str = txn.get('date', '')
            if isinstance(date_str, str) and date_str:
                try:
                    txn['date'] = fields.Date.to_date(date_str)
                except (ValueError, TypeError):
                    txn['date'] = fields.Date.today()

        parsed_data['balance_start'] = self._parse_vnd_amount(parsed_data.get('balance_start', 0))
        parsed_data['balance_end'] = self._parse_vnd_amount(parsed_data.get('balance_end', 0))

        return parsed_data
