# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging
import re

from odoo import _, models

_logger = logging.getLogger(__name__)

# Scoring weights
SCORE_INVOICE_NUMBER = 70
SCORE_AMOUNT_EXACT = 50
SCORE_PARTNER_EXACT = 30
SCORE_PARTNER_FUZZY = 10
SCORE_SO_PO_MATCH = 20
AMBIGUITY_THRESHOLD = 10

INVOICE_PATTERNS = [
    r'\b(?:HD|HĐ|INV|SO|PO)[-:\s]?(\d{4,10})\b',
    r'\b(\d{5,10})\b',
]
FEE_KEYWORDS = [
    'PHI NGAN HANG', 'PHI NH', 'PHI CK', 'PHI CHUYEN KHOAN',
    'PHI GIAO DICH', 'FEE', 'SERVICE CHARGE', 'PHI DV',
]


class AccountBankStatement(models.Model):
    _inherit = 'account.bank.statement'

    def action_auto_reconcile_vn(self):
        """Run VN auto-reconciliation scoring engine on unreconciled lines."""
        self.ensure_one()
        ICP = self.env['ir.config_parameter'].sudo()
        tolerance = float(ICP.get_param(
            'l10n_vn_bank_statement_import.match_tolerance', 2000.0,
        ))
        fee_account_code = ICP.get_param(
            'l10n_vn_bank_statement_import.fee_account_code', '6427',
        )

        results = {'matched': 0, 'needs_review': 0, 'fees': 0, 'unmatched': 0}

        for st_line in self.line_ids:
            if st_line.is_reconciled:
                continue

            payment_ref = (st_line.payment_ref or '').upper()

            # Bank fee detection
            if self._is_bank_fee(payment_ref):
                if self._post_bank_fee(st_line, fee_account_code):
                    results['fees'] += 1
                else:
                    results['unmatched'] += 1
                continue

            # Invoice matching
            candidates = self._find_candidates(st_line, tolerance)

            if not candidates:
                results['unmatched'] += 1
                continue

            candidates.sort(key=lambda c: c['score'], reverse=True)
            top = candidates[0]

            if len(candidates) > 1 and (top['score'] - candidates[1]['score']) < AMBIGUITY_THRESHOLD:
                desc = ', '.join(
                    f"{c['invoice'].name} (score={c['score']})"
                    for c in candidates[:3]
                )
                st_line.move_id.message_post(
                    body=_('Auto-reconcile: Ambiguous match. Top candidates: %s', desc),
                )
                results['needs_review'] += 1
                continue

            if self._reconcile_line_with_invoice(st_line, top['invoice']):
                results['matched'] += 1
            else:
                results['unmatched'] += 1

        msg = _(
            'Auto-reconcile results: %d matched, %d fees, %d needs review, %d unmatched.',
            results['matched'], results['fees'],
            results['needs_review'], results['unmatched'],
        )
        _logger.info('Statement %s: %s', self.name, msg)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Auto-Reconcile'),
                'message': msg,
                'type': 'success' if results['matched'] > 0 else 'warning',
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }

    def _is_bank_fee(self, payment_ref):
        ref_upper = (payment_ref or '').upper()
        return any(kw in ref_upper for kw in FEE_KEYWORDS)

    def _post_bank_fee(self, st_line, fee_account_code):
        fee_account = self.env['account.account'].sudo().search([
            ('code', '=', fee_account_code),
            ('company_ids', 'in', st_line.company_id.id),
        ], limit=1)
        if not fee_account:
            return False

        _liquidity, suspense, _other = st_line._seek_for_lines()
        if not suspense:
            return False

        suspense.with_context(skip_account_move_synchronization=True).write({
            'account_id': fee_account.id,
        })
        return True

    def _find_candidates(self, st_line, tolerance):
        candidates = []
        payment_ref = (st_line.payment_ref or '').upper()
        amount = abs(st_line.amount)

        if st_line.amount > 0:
            move_types = ('out_invoice', 'in_refund')
        else:
            move_types = ('in_invoice', 'out_refund')

        open_invoices = self.env['account.move'].sudo().search([
            ('move_type', 'in', move_types),
            ('payment_state', 'in', ('not_paid', 'partial')),
            ('state', '=', 'posted'),
            ('company_id', '=', st_line.company_id.id),
        ])

        if not open_invoices:
            return candidates

        extracted_refs = self._extract_invoice_numbers(payment_ref)

        for invoice in open_invoices:
            score = 0

            inv_name = (invoice.name or '').upper()
            inv_ref = (invoice.ref or '').upper()
            einvoice_num = ''
            if hasattr(invoice, 'l10n_vn_e_invoice_number'):
                einvoice_num = (invoice.l10n_vn_e_invoice_number or '').upper()

            for ref in extracted_refs:
                if ref in inv_name or ref in inv_ref or ref in einvoice_num:
                    score += SCORE_INVOICE_NUMBER
                    break

            if not score and inv_ref and len(inv_ref) >= 5 and inv_ref in payment_ref:
                score += SCORE_INVOICE_NUMBER

            residual = abs(invoice.amount_residual)
            if abs(residual - amount) <= tolerance:
                score += SCORE_AMOUNT_EXACT

            if st_line.partner_id and st_line.partner_id == invoice.partner_id:
                score += SCORE_PARTNER_EXACT
            elif self._fuzzy_partner_match(payment_ref, invoice.partner_id):
                score += SCORE_PARTNER_FUZZY

            origin = (invoice.invoice_origin or '').upper()
            if origin:
                so_matches = re.findall(r'(S\d{4,10}|SO\d{4,10}|PO\d{4,10})', payment_ref)
                for so in so_matches:
                    if so in origin:
                        score += SCORE_SO_PO_MATCH
                        break

            if score > 0:
                candidates.append({'invoice': invoice, 'score': score})

        return candidates

    def _extract_invoice_numbers(self, text):
        found = set()
        for pattern in INVOICE_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                found.add(match.group(match.lastindex or 0))
        return list(found)

    def _fuzzy_partner_match(self, payment_ref, partner):
        if not partner:
            return False
        partner_name = (partner.name or '').upper()
        if len(partner_name) >= 4 and partner_name in payment_ref:
            return True
        partner_ref = (partner.ref or '').upper()
        if partner_ref and len(partner_ref) >= 3 and partner_ref in payment_ref:
            return True
        return False

    def _reconcile_line_with_invoice(self, st_line, invoice):
        _liquidity, suspense, _other = st_line._seek_for_lines()
        if not suspense:
            return False

        invoice_line = invoice.line_ids.filtered(
            lambda l: l.account_id.account_type in ('asset_receivable', 'liability_payable')
                      and not l.reconciled
        )
        if not invoice_line:
            return False

        try:
            (suspense + invoice_line[:1]).reconcile()
            _logger.info(
                'Auto-reconciled statement line "%s" with invoice %s',
                st_line.payment_ref, invoice.name,
            )
            return True
        except Exception as e:
            _logger.warning(
                'Failed to reconcile "%s" with %s: %s',
                st_line.payment_ref, invoice.name, str(e),
            )
            return False
