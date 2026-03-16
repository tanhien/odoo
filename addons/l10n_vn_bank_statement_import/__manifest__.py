{
    'name': 'Vietnam - Bank Statement Import',
    'icon': '/account/static/description/l10n.png',
    'version': '2.0',
    'countries': ['vn'],
    'category': 'Accounting/Localizations',
    'summary': 'Import Vietnamese bank statements from XLS/PDF into payments with bill matching',
    'depends': [
        'l10n_vn',
        'l10n_vn_einvoice_import',
    ],
    'data': [
        'security/ir.model.access.csv',
        'wizard/bank_statement_import_wizard_views.xml',
        'views/res_config_settings_views.xml',
        'views/account_menuitem.xml',
    ],
    'installable': True,
    'author': 'Custom',
    'license': 'LGPL-3',
    'external_dependencies': {
        'python': ['xlrd'],
    },
}
