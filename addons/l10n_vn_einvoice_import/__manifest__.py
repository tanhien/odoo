{
    'name': 'Vietnam - E-Invoice Import',
    'icon': '/account/static/description/l10n.png',
    'version': '1.0',
    'countries': ['vn'],
    'category': 'Accounting/Localizations',
    'summary': 'Import Vietnamese e-invoices from XML and PDF files',
    'description': """
Vietnam - E-Invoice Import
===========================
Import e-invoices in TCT XML format or PDF (via LLM OCR) and create
vendor bills (account.move) automatically.
    """,
    'depends': [
        'l10n_vn',
    ],
    'data': [
        'security/ir.model.access.csv',
        'wizard/einvoice_import_wizard_views.xml',
        'views/res_config_settings_views.xml',
        'views/account_menuitem.xml',
    ],
    'installable': True,
    'author': 'Custom',
    'license': 'LGPL-3',
}
