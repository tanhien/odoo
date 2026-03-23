import logging

from markupsafe import Markup

from odoo import api, models, _, Command

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    @api.model
    def _get_import_file_type(self, file_data):
        # EXTENDS 'account'
        if file_data.get('mimetype') in ('image/jpeg', 'image/png', 'image/jpg'):
            return 'image'
        return super()._get_import_file_type(file_data)

    def _get_edi_decoder(self, file_data, new=False):
        # EXTENDS 'account'
        ocr_service = self.env['account.ai.ocr.service']
        if (
            ocr_service._is_enabled()
            and file_data.get('import_file_type') in ('pdf', 'image')
        ):
            # Use low priority (5) so EDI decoders (priority 20) always win
            parent_decoder = super()._get_edi_decoder(file_data, new)
            if parent_decoder and parent_decoder.get('priority', 0) > 5:
                return parent_decoder
            return {
                'decoder': self._decode_with_ai_ocr,
                'priority': 5,
            }
        return super()._get_edi_decoder(file_data, new)

    def _should_attach_to_record(self, attachment):
        # EXTENDS 'account'
        if attachment and not attachment.res_field and attachment.mimetype in ('image/jpeg', 'image/png'):
            return True
        return super()._should_attach_to_record(attachment)

    # -------------------------------------------------------------------------
    # AI OCR Decoder
    # -------------------------------------------------------------------------

    def _decode_with_ai_ocr(self, invoice, file_data, new):
        """Decoder function for the document import framework.

        :param invoice: The account.move record to populate.
        :param file_data: Dict with file info (name, raw, mimetype, etc.)
        :param new: Whether the invoice was newly created.
        :returns: None on success, or a string reason on failure.
        """
        if invoice.invoice_line_ids:
            return invoice._reason_cannot_decode_has_invoice_lines()

        ocr_service = self.env['account.ai.ocr.service']

        # Convert file to images
        if file_data.get('import_file_type') == 'pdf':
            try:
                images = ocr_service._convert_pdf_to_images(file_data['raw'])
            except Exception as e:
                _logger.warning("PDF to image conversion failed: %s", e)
                return _("Failed to convert PDF to images: %s", str(e))
        else:
            images = [file_data['raw']]

        if not images:
            return _("No images could be extracted from the file.")

        # Call Ollama for extraction
        try:
            extracted = ocr_service._extract_invoice_data(images)
        except Exception as e:
            _logger.warning("AI OCR extraction failed: %s", e)
            return _("AI OCR extraction failed: %s", str(e))

        if not extracted:
            return _("AI OCR could not extract any data from the document.")

        # Populate the invoice
        self._populate_invoice_from_ocr(invoice, extracted, new)
        return None

    def _populate_invoice_from_ocr(self, invoice, data, new):
        """Fill in invoice fields from OCR-extracted data.

        :param invoice: The account.move record.
        :param data: Dict with extracted invoice data from AI.
        :param new: Whether the invoice was newly created.
        """
        logs = []

        with invoice._get_edi_creation() as invoice:
            vals = {}

            # --- Partner ---
            partner = self._match_ocr_partner(
                invoice.company_id,
                vendor_name=data.get('vendor_name'),
                vendor_vat=data.get('vendor_vat'),
            )
            if partner:
                invoice.partner_id = partner
            elif data.get('vendor_name'):
                logs.append(_(
                    "Could not match vendor '%(name)s' to an existing partner.",
                    name=data['vendor_name'],
                ))

            # --- Currency ---
            currency_code = data.get('currency')
            if currency_code:
                currency = self.env['res.currency'].with_context(active_test=False).search(
                    [('name', '=', currency_code.upper())], limit=1,
                )
                if currency:
                    vals['currency_id'] = currency.id
                else:
                    logs.append(_(
                        "Currency '%(code)s' not found.",
                        code=currency_code,
                    ))

            # --- Dates ---
            if data.get('invoice_date'):
                vals['invoice_date'] = data['invoice_date']
            if data.get('due_date'):
                vals['invoice_date_due'] = data['due_date']

            # --- Reference ---
            if data.get('invoice_number'):
                if invoice.is_sale_document(include_receipts=True):
                    vals['name'] = data['invoice_number']
                else:
                    vals['ref'] = data['invoice_number']

            if data.get('payment_reference'):
                vals['payment_reference'] = data['payment_reference']

            if data.get('notes'):
                vals['narration'] = data['notes']

            # --- Invoice Lines ---
            line_commands = []
            for line_data in (data.get('lines') or []):
                line_vals = self._prepare_ocr_invoice_line(invoice, line_data)
                if line_vals:
                    line_commands.append(Command.create(line_vals))

            if line_commands:
                vals['invoice_line_ids'] = line_commands

            if vals:
                invoice.write(vals)

        # Post import log to chatter
        body = Markup("<strong>%s</strong>") % _("Invoice imported via AI OCR")
        if logs:
            body += Markup("<ul>%s</ul>") % Markup().join(
                Markup("<li>%s</li>") % log for log in logs
            )
        invoice.message_post(body=body)

    def _match_ocr_partner(self, company, vendor_name=None, vendor_vat=None):
        """Match OCR-extracted vendor info to an existing res.partner.

        Uses the standard _retrieve_partner() method which searches
        by VAT first (most reliable), then by name.
        """
        if not vendor_name and not vendor_vat:
            return self.env['res.partner']
        return self.env['res.partner']._retrieve_partner(
            name=vendor_name,
            vat=vendor_vat,
            company=company,
        )

    def _prepare_ocr_invoice_line(self, invoice, line_data):
        """Convert a single OCR line dict to invoice line vals.

        :param invoice: The account.move record (for tax lookup context).
        :param line_data: Dict with keys: description, quantity, unit_price, tax_percent
        :returns: Dict of vals for account.move.line creation.
        """
        description = line_data.get('description')
        if not description:
            return None

        vals = {
            'display_type': 'product',
            'name': description,
            'quantity': float(line_data.get('quantity') or 1),
            'price_unit': float(line_data.get('unit_price') or 0),
        }

        # Tax matching
        tax_percent = line_data.get('tax_percent')
        if tax_percent is not None:
            tax_type = 'purchase' if invoice.is_purchase_document(include_receipts=True) else 'sale'
            tax = self.env['account.tax'].search([
                *self.env['account.tax']._check_company_domain(invoice.company_id),
                ('amount', '=', float(tax_percent)),
                ('amount_type', '=', 'percent'),
                ('type_tax_use', '=', tax_type),
            ], limit=1)
            if tax:
                vals['tax_ids'] = [Command.set(tax.ids)]

        return vals
