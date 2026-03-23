import base64
import io
import logging
import re
from datetime import datetime

from odoo import fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Column header keywords (Vietnamese, with and without diacritics)
HEADER_KEYWORDS = {
    'content': ['nội dung', 'noi dung', 'diễn giải', 'dien giai', 'mô tả', 'mo ta'],
    'deposit': ['số tiền gửi', 'so tien gui', 'tiền gửi', 'tien gui', 'có', 'co', 'credit'],
    'withdrawal': ['số tiền rút', 'so tien rut', 'tiền rút', 'tien rut', 'nợ', 'no', 'debit'],
    'date': ['ngày giao dịch', 'ngay giao dich', 'ngày', 'ngay', 'date'],
    'ref': ['số giao dịch', 'so giao dich', 'mã gd', 'ma gd', 'số ct', 'so ct', 'ref'],
}


class AccountBankStatementExcelImport(models.TransientModel):
    _name = 'account.bank.statement.excel.import'
    _description = 'Import Bank Statement from Excel'

    file_data = fields.Binary(string="Excel File", required=True)
    file_name = fields.Char(string="File Name")
    journal_id = fields.Many2one(
        'account.journal',
        string="Bank Journal",
        required=True,
        domain=[('type', '=', 'bank')],
    )

    def action_import(self):
        """Parse Excel bank statement and create payment records."""
        self.ensure_one()

        if not self.file_data:
            raise UserError(_("Please upload an Excel file."))

        if self.file_name and not self.file_name.lower().endswith(('.xlsx', '.xls')):
            raise UserError(_("Please upload an Excel file (.xlsx or .xls)."))

        file_content = base64.b64decode(self.file_data)
        is_xls = self.file_name and self.file_name.lower().endswith('.xls')

        # Read all rows as list of lists (unified format for .xls and .xlsx)
        try:
            if is_xls:
                rows = self._read_xls(file_content)
            else:
                rows = self._read_xlsx(file_content)
        except UserError:
            raise
        except Exception as e:
            raise UserError(_("Cannot read Excel file: %s", str(e)))

        if not rows:
            raise UserError(_("The Excel file is empty."))

        # Find header row and column mapping
        col_map = self._find_header_columns(rows)
        if not col_map.get('header_row'):
            raise UserError(_(
                "Cannot find header row in the Excel file. "
                "Expected columns: Nội dung, Số tiền gửi, Số tiền rút, Ngày giao dịch"
            ))

        # Parse data rows and create payments
        payments = self._parse_and_create_payments(rows, col_map)

        if not payments:
            raise UserError(_("No valid transactions found in the Excel file."))

        # Return action to show created payments
        action = {
            'name': _('Imported Payments (%s)', self.file_name or 'Excel'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.payment',
            'domain': [('id', 'in', payments.ids)],
            'context': self.env.context,
        }
        if len(payments) == 1:
            action.update({
                'views': [[False, 'form']],
                'view_mode': 'form',
                'res_id': payments[0].id,
            })
        else:
            action.update({
                'views': [[False, 'list'], [False, 'form']],
                'view_mode': 'list,form',
            })
        return action

    # -------------------------------------------------------------------------
    # Excel readers - return unified list-of-lists format
    # -------------------------------------------------------------------------

    def _read_xlsx(self, file_content):
        """Read .xlsx file using openpyxl. Returns list of row-lists."""
        try:
            import openpyxl
        except ImportError:
            raise UserError(_("The 'openpyxl' library is required for .xlsx files. "
                              "Install with: pip install openpyxl"))

        wb = openpyxl.load_workbook(io.BytesIO(file_content), data_only=True)
        ws = wb.active
        rows = []
        for row in ws.iter_rows(values_only=True):
            rows.append(list(row))
        wb.close()
        return rows

    def _read_xls(self, file_content):
        """Read .xls file using xlrd. Returns list of row-lists."""
        try:
            import xlrd
        except ImportError:
            raise UserError(_("The 'xlrd' library is required for .xls files. "
                              "Install with: pip install xlrd"))

        wb = xlrd.open_workbook(file_contents=file_content)
        ws = wb.sheet_by_index(0)
        rows = []
        for row_idx in range(ws.nrows):
            row_values = []
            for col_idx in range(ws.ncols):
                cell = ws.cell(row_idx, col_idx)
                # Convert xlrd date cells to datetime
                if cell.ctype == xlrd.XL_CELL_DATE:
                    try:
                        date_tuple = xlrd.xldate_as_tuple(cell.value, wb.datemode)
                        row_values.append(datetime(*date_tuple))
                    except Exception:
                        row_values.append(cell.value)
                else:
                    row_values.append(cell.value)
            rows.append(row_values)
        return rows

    # -------------------------------------------------------------------------
    # Header detection and data parsing
    # -------------------------------------------------------------------------

    def _find_header_columns(self, rows):
        """Scan rows to find the header row and map columns.

        :param rows: list of row-lists (values)
        :returns: dict with 'header_row' (0-indexed) and column indices
        """
        col_map = {'header_row': None}

        # Scan first 20 rows to find header
        for row_idx, row in enumerate(rows[:20]):
            row_texts = [str(cell or '').strip().lower() for cell in row]

            # Check if this row contains enough known headers
            found_cols = {}
            for cell_idx, text in enumerate(row_texts):
                if not text:
                    continue
                for field_name, keywords in HEADER_KEYWORDS.items():
                    if field_name in found_cols:
                        continue
                    for kw in keywords:
                        if kw in text:
                            found_cols[field_name] = cell_idx
                            break

            # Need at least content + one of deposit/withdrawal
            if 'content' in found_cols and ('deposit' in found_cols or 'withdrawal' in found_cols):
                col_map['header_row'] = row_idx
                col_map.update(found_cols)
                _logger.info(
                    "Found header at row %s: %s",
                    row_idx,
                    {k: v for k, v in col_map.items() if k != 'header_row'},
                )
                break

        return col_map

    def _parse_and_create_payments(self, rows, col_map):
        """Parse data rows and create payment records.

        :param rows: list of row-lists (values)
        :param col_map: dict with header_row and column indices
        :returns: account.payment recordset
        """
        header_row = col_map['header_row']
        content_col = col_map.get('content')
        deposit_col = col_map.get('deposit')
        withdrawal_col = col_map.get('withdrawal')
        date_col = col_map.get('date')
        ref_col = col_map.get('ref')

        payments = self.env['account.payment']
        skipped = 0

        for row in rows[header_row + 1:]:
            # Safely get cell value by column index
            def cell(col):
                if col is not None and col < len(row):
                    return row[col]
                return None

            content = str(cell(content_col) or '').strip()
            deposit = self._parse_amount(cell(deposit_col))
            withdrawal = self._parse_amount(cell(withdrawal_col))
            date_val = self._parse_date(cell(date_col))
            ref_val = str(cell(ref_col) or '').strip()

            # Determine payment type and amount
            if deposit and deposit > 0:
                payment_type = 'inbound'
                amount = deposit
            elif withdrawal and withdrawal > 0:
                payment_type = 'outbound'
                amount = withdrawal
            else:
                skipped += 1
                continue

            # Skip rows without content or date
            if not content and not date_val:
                skipped += 1
                continue

            if not date_val:
                date_val = fields.Date.context_today(self)

            # Try to match partner from content
            partner = self._extract_partner(content)

            # Build memo with all info
            memo_parts = []
            if content:
                memo_parts.append(content)
            if ref_val:
                memo_parts.append(f"[Ref: {ref_val}]")
            if self.file_name:
                memo_parts.append(f"[File: {self.file_name}]")
            memo = '\n'.join(memo_parts)

            # Create payment
            try:
                payment_vals = {
                    'payment_type': payment_type,
                    'partner_type': 'customer',
                    'amount': amount,
                    'date': date_val,
                    'journal_id': self.journal_id.id,
                    'memo': memo,
                }
                if partner:
                    payment_vals['partner_id'] = partner.id
                if ref_val:
                    payment_vals['payment_reference'] = ref_val

                payment = self.env['account.payment'].create(payment_vals)
                payments |= payment
            except Exception as e:
                _logger.warning("Failed to create payment for row: %s - %s", content[:50], e)
                skipped += 1

        # Auto-post all payments so journal entries are created for reconciliation
        if payments:
            try:
                payments.action_post()
            except UserError as e:
                _logger.warning("Failed to post payments: %s", e)
                raise UserError(_(
                    "Payments were created but could not be confirmed.\n\n"
                    "%(error)s\n\n"
                    "Please configure the Outstanding Receipts/Payments Account:\n"
                    "Accounting → Configuration → Journals → %(journal)s → "
                    "Incoming/Outgoing Payments tab → Outstanding Account column.",
                    error=e,
                    journal=self.journal_id.display_name,
                ))
            except Exception as e:
                _logger.warning("Failed to post some payments: %s", e)

        if skipped:
            _logger.info("Bank statement import: created %d payments, skipped %d rows",
                         len(payments), skipped)

        return payments

    # -------------------------------------------------------------------------
    # Value parsers
    # -------------------------------------------------------------------------

    def _parse_amount(self, value):
        """Parse an amount value from Excel cell, handling VND formatting.

        VND uses dots as thousand separators (31.818 = 31818).
        """
        if value is None:
            return 0

        if isinstance(value, (int, float)):
            if isinstance(value, float):
                str_val = str(value)
                if '.' in str_val:
                    decimal_part = str_val.split('.')[1].rstrip('0')
                    if len(decimal_part) == 3:
                        return int(value * 1000)
            return abs(int(round(value))) if value else 0

        if isinstance(value, str):
            cleaned = value.strip().replace('.', '').replace(',', '').replace(' ', '')
            cleaned = re.sub(r'[^\d]', '', cleaned)
            try:
                return int(cleaned) if cleaned else 0
            except ValueError:
                return 0

        return 0

    def _parse_date(self, value):
        """Parse a date value from Excel cell."""
        if value is None:
            return None

        if isinstance(value, datetime):
            return value.date()

        if hasattr(value, 'date') and callable(getattr(value, 'date', None)):
            return value.date()

        if isinstance(value, str):
            value = value.strip()
            for fmt in ('%d-%m-%Y %H:%M:%S', '%d-%m-%Y', '%d/%m/%Y %H:%M:%S',
                        '%d/%m/%Y', '%Y-%m-%d', '%m/%d/%Y'):
                try:
                    return datetime.strptime(value, fmt).date()
                except ValueError:
                    continue

        return None

    def _extract_partner(self, content):
        """Try to extract and match a partner from transaction content.

        Strategy:
        1. Extract company-like names (CTY/CONG TY patterns)
        2. Split content by common delimiters and try each segment
        3. Search all existing partners whose name appears in the content

        :param content: Transaction description string
        :returns: res.partner record or empty recordset
        """
        if not content:
            return self.env['res.partner']

        content_upper = content.upper().strip()

        # Strategy 1: Extract company name patterns from content
        # Vietnamese bank statements often contain: "CTY TNHH ABC XYZ" or "CONG TY CP ABC"
        company_patterns = [
            # Full company name with type: CTY TNHH TM DV ABC XYZ
            r'((?:CTY|CONG TY|CT|C\.TY)\s*(?:TNHH|CP|CO PHAN|TNHH MTV|TNHH SX TM|TNHH TM DV|TNHH DV|TNHH TM|TNHH SX)?\s*.+?)(?:\s*[-,]|\s*CKN|\s*STK|\s*TAI\s*KHOAN|\s*NGAN\s*HANG|\s*NH\s|\s*TMCP|\s*$)',
            # After dash: "- CTY TNHH ABC - Ngan hang..."
            r'-\s*((?:CTY|CONG TY|CT)\s*(?:TNHH|CP|CO PHAN)?\s*.+?)\s*(?:-|$)',
        ]

        for pattern in company_patterns:
            match = re.search(pattern, content_upper, re.IGNORECASE)
            if match:
                name_candidate = match.group(1).strip().rstrip('-').strip()
                if len(name_candidate) > 5:
                    partner = self._search_partner_flexible(name_candidate)
                    if partner:
                        return partner

        # Strategy 2: Search existing partners whose name appears IN the content
        # This handles cases where partner name is embedded in the description
        partners = self.env['res.partner'].search([
            ('customer_rank', '>', 0),
            ('is_company', '=', True),
        ], limit=200)

        best_match = None
        best_len = 0
        for p in partners:
            p_name = (p.name or '').upper().strip()
            if len(p_name) > 3 and p_name in content_upper:
                # Prefer longer name matches (more specific)
                if len(p_name) > best_len:
                    best_match = p
                    best_len = len(p_name)

        if best_match:
            return best_match

        # Strategy 3: Split content by delimiters and try each segment
        segments = re.split(r'[-/|]', content)
        for segment in segments:
            segment = segment.strip()
            if len(segment) > 5:
                partner = self.env['res.partner']._retrieve_partner(name=segment)
                if partner:
                    return partner

        return self.env['res.partner']

    def _search_partner_flexible(self, name):
        """Search partner with flexible name matching.

        Tries exact ilike first, then partial words.
        """
        # Direct ilike search
        partner = self.env['res.partner'].search([
            ('name', 'ilike', name),
        ], limit=1)
        if partner:
            return partner

        # Try without common prefixes/suffixes
        cleaned = re.sub(
            r'^(CTY|CONG TY|CT|C\.TY)\s*(TNHH|CP|CO PHAN|TNHH MTV)?\s*(TM\s*DV|SX\s*TM|DV|TM|SX)?\s*',
            '', name, flags=re.IGNORECASE,
        ).strip()
        if cleaned and len(cleaned) > 3:
            partner = self.env['res.partner'].search([
                ('name', 'ilike', cleaned),
            ], limit=1)
            if partner:
                return partner

        return self.env['res.partner']
