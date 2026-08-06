{
    'name': 'Odoo School Coworking Management',
    'summary': 'Manage coworking locations, resources, bookings, memberships, and visits.',
    'author': 'Odoo School Student',
    'website': 'https://odoo.school/',
    'category': 'Customizations',
    'version': '19.0.1.0.0',
    'license': 'OPL-1',
    'depends': [
        'base',
        'mail',
        'product',
        'calendar',
        'web',
    ],
    'data': [
        'security/os_coworking_groups.xml',
        'views/os_coworking_menu_views.xml',
    ],
    'images': ['static/description/icon.png'],
    'installable': True,
    'application': True,
    'auto_install': False,
}
