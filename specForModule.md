# Odoo 19.0 - Hướng dẫn phát triển Module

## Mục lục

1. [Setup môi trường phát triển](#1-setup-môi-trường-phát-triển)
2. [Cấu trúc module](#2-cấu-trúc-module)
3. [Manifest file](#3-manifest-file---manifestpy)
4. [Models & ORM](#4-models--orm)
5. [Views & UI](#5-views--ui)
6. [Security & Access Control](#6-security--access-control)
7. [Controllers (HTTP)](#7-controllers-http)
8. [Data files & Demo](#8-data-files--demo)
9. [Wizards (TransientModel)](#9-wizards-transientmodel)
10. [Frontend (OWL/JS)](#10-frontend-owljs)
11. [Reports](#11-reports)
12. [Testing](#12-testing)
13. [Migration & Upgrade](#13-migration--upgrade)
14. [Deploy](#14-deploy)
15. [Best practices](#15-best-practices)

---

## 1. Setup môi trường phát triển

### 1.1 Yêu cầu hệ thống

| Thành phần | Phiên bản |
|------------|-----------|
| Python | 3.10 - 3.13 |
| PostgreSQL | >= 13 |
| Node.js | (cho biên dịch assets) |
| Git | Bất kỳ |

### 1.2 Cài đặt

```bash
# 1. Clone source code
git clone https://github.com/odoo/odoo.git -b 19.0 --depth 1
git clone https://github.com/tanhien/odoo.git -b 19.0 --depth 1

# 2. Tạo virtual environment
python -m venv venv
source venv/bin/activate       # Linux/Mac
venv\Scripts\activate          # Windows

# 3. Cài đặt dependencies
pip install -r requirements.txt

# 4. Tạo database PostgreSQL
createdb mydb

# 5. Khởi chạy Odoo
python odoo-bin -d mydb --addons-path=addons,my_addons -i base
```

### 1.3 Cấu hình file `odoo.conf`

```ini
[options]
; Database
db_host = localhost
db_port = 5432
db_user = odoo
db_password = odoo
db_name = mydb

; Đường dẫn addons (quan trọng - thêm thư mục chứa module custom)
addons_path = ./addons,./my_custom_addons

; Server
http_port = 8069
xmlrpc_port = 8069

; Development
dev_mode = reload,assets    ; Auto-reload khi thay đổi code

; Logging
log_level = debug
log_handler = odoo.addons.my_module:DEBUG
```

### 1.4 Khởi chạy ở chế độ Development

```bash
# Khởi chạy với dev mode (auto-reload khi thay đổi Python code)
python odoo-bin -c odoo.conf --dev=reload

# Cài đặt/cập nhật module
python odoo-bin -d mydb -u my_module        # Update module
python odoo-bin -d mydb -i my_module        # Install module

# Khởi chạy với log debug cho module cụ thể
python odoo-bin -d mydb --log-handler=odoo.addons.my_module:DEBUG
```

### 1.5 Tạo skeleton module bằng scaffold

```bash
# Tạo module mới từ template có sẵn
python odoo-bin scaffold my_module ./my_custom_addons

# Templates có sẵn: default, theme, l10n_payroll
python odoo-bin scaffold -t theme my_theme ./my_custom_addons
```

---

## 2. Cấu trúc Module

### 2.1 Cấu trúc thư mục chuẩn

```
my_module/
├── __init__.py                 # Import models, controllers, wizards
├── __manifest__.py             # Metadata, dependencies, data files
│
├── models/                     # Business logic (ORM models)
│   ├── __init__.py
│   ├── my_model.py
│   └── res_partner.py          # Mở rộng model có sẵn
│
├── views/                      # XML view definitions
│   ├── my_model_views.xml      # Form, list, kanban views
│   ├── res_partner_views.xml   # Mở rộng views có sẵn
│   └── menu_views.xml          # Menu items
│
├── security/                   # Access control
│   ├── ir.model.access.csv     # Model-level access rights
│   └── security.xml            # Groups & record rules
│
├── controllers/                # HTTP controllers (web routes)
│   ├── __init__.py
│   └── main.py
│
├── wizards/                    # Wizard (TransientModel)
│   ├── __init__.py
│   ├── my_wizard.py
│   └── my_wizard_views.xml
│
├── data/                       # Default data (XML/CSV)
│   ├── data.xml
│   └── ir_cron_data.xml
│
├── demo/                       # Demo data (chỉ load khi demo mode)
│   └── demo.xml
│
├── report/                     # Report templates
│   ├── report_templates.xml
│   └── report_actions.xml
│
├── static/                     # Static assets
│   ├── description/            # Module icon & screenshots
│   │   ├── icon.png            # 100x100px module icon
│   │   └── icon.svg
│   ├── src/                    # Source code JS/SCSS
│   │   ├── components/         # OWL components (.js, .xml, .scss)
│   │   └── scss/
│   └── tests/                  # Frontend unit tests
│       └── my_component.test.js
│
├── tests/                      # Python unit tests
│   ├── __init__.py
│   ├── test_my_model.py
│   └── test_access_rights.py
│
├── migrations/                 # Migration scripts
│   └── 19.0.1.1/
│       ├── pre-migrate.py
│       └── post-migrate.py
│
└── i18n/                       # Translations
    ├── my_module.pot            # Translation template
    └── vi_VN.po                 # Vietnamese translation
```

### 2.2 File `__init__.py` gốc

```python
# my_module/__init__.py
from . import models
from . import controllers
from . import wizards
```

```python
# my_module/models/__init__.py
from . import my_model
from . import res_partner  # extend existing model
```

---

## 3. Manifest file - `__manifest__.py`

File khai báo metadata, dependencies và tài nguyên của module.

```python
# my_module/__manifest__.py
{
    'name': 'My Custom Module',
    'version': '19.0.1.0.0',         # server_version.module_version
    'summary': 'Short description of the module',
    'description': """
        Long description of the module's purpose.
        Can use reStructuredText format.
    """,
    'author': 'My Company',
    'website': 'https://www.mycompany.com',
    'license': 'LGPL-3',
    'category': 'Sales/CRM',         # Phân loại module
    'sequence': 10,                   # Thứ tự hiển thị

    # Module dependencies (bắt buộc phải cài trước)
    'depends': [
        'base',                       # Module kernel (luôn cần)
        'mail',                       # Nếu cần chatter/messaging
        'sale',                       # Nếu mở rộng Sales
    ],

    # Data files - load theo thứ tự khai báo
    'data': [
        'security/security.xml',          # Groups TRƯỚC access rules
        'security/ir.model.access.csv',   # Access rules
        'views/my_model_views.xml',
        'views/menu_views.xml',
        'data/data.xml',
        'data/ir_cron_data.xml',
        'report/report_actions.xml',
        'report/report_templates.xml',
        'wizards/my_wizard_views.xml',
    ],

    # Demo data - chỉ load khi tạo database với demo data
    'demo': [
        'demo/demo.xml',
    ],

    # Frontend assets (JS, SCSS, XML templates)
    'assets': {
        'web.assets_backend': [
            'my_module/static/src/**/*.js',
            'my_module/static/src/**/*.xml',
            'my_module/static/src/**/*.scss',
        ],
        'web.assets_frontend': [
            'my_module/static/src/public/**/*.js',
        ],
        'web.assets_unit_tests': [
            'my_module/static/tests/**/*.test.js',
        ],
    },

    'installable': True,              # Có thể cài đặt
    'auto_install': False,            # Tự cài khi dependencies đủ?
    'application': True,              # Hiển thị như app chính?

    # Hooks (optional)
    'pre_init_hook': 'pre_init_hook',
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'post_load': 'post_load',
}
```

### 3.1 Quy ước version

```
19.0.1.0.0
 │   │ │ │
 │   │ │ └── Patch (bug fix)
 │   │ └──── Minor (tính năng nhỏ)
 │   └────── Major (thay đổi lớn)
 └────────── Odoo server version
```

### 3.2 Asset Bundles phổ biến

| Bundle | Mô tả |
|--------|--------|
| `web.assets_backend` | Backend web client (sau đăng nhập) |
| `web.assets_frontend` | Frontend website (public pages) |
| `web.assets_common` | Dùng chung backend + frontend |
| `web.assets_unit_tests` | Frontend unit tests |
| `web.assets_tests` | Frontend tour/integration tests |
| `point_of_sale._assets` | POS frontend |

---

## 4. Models & ORM

### 4.1 Các loại Model

```python
from odoo import models, fields, api

# Model thường - tạo bảng trong database
class MyModel(models.Model):
    _name = 'my.module.model'           # Tên kỹ thuật (unique)
    _description = 'My Model'           # Mô tả
    _order = 'sequence, name'           # Thứ tự mặc định
    _rec_name = 'name'                  # Field hiển thị tên bản ghi

# TransientModel - bảng tạm, tự xóa sau thời gian
# Dùng cho wizards, popup nhập liệu
class MyWizard(models.TransientModel):
    _name = 'my.module.wizard'
    _description = 'My Wizard'

# AbstractModel - không tạo bảng, chỉ dùng để kế thừa (mixin)
class MyMixin(models.AbstractModel):
    _name = 'my.module.mixin'
    _description = 'My Mixin'
```

### 4.2 Kế thừa Model

```python
# === Cách 1: Mở rộng model có sẵn (thêm field/method) ===
# KHÔNG tạo bảng mới, thêm trực tiếp vào model gốc
class ResPartner(models.Model):
    _inherit = 'res.partner'                # Mở rộng res.partner

    my_custom_field = fields.Char('My Field')

    def my_custom_method(self):
        # Có thể gọi super() để chain
        result = super().my_custom_method()
        return result


# === Cách 2: Kế thừa tạo model mới (prototype inheritance) ===
# Tạo bảng MỚI, copy tất cả fields từ model cha
class MyPartner(models.Model):
    _name = 'my.partner'
    _inherit = 'res.partner'                # Copy từ res.partner
    _description = 'My Partner'


# === Cách 3: Delegation inheritance (_inherits) ===
# Tạo bảng mới, liên kết Many2one với model cha
# Tự động truy cập fields của cha qua delegation
class Employee(models.Model):
    _name = 'hr.employee'
    _inherits = {'res.partner': 'address_id'}

    address_id = fields.Many2one('res.partner', required=True, ondelete='cascade')
    job_title = fields.Char()
    # Có thể truy cập employee.name (từ res.partner)


# === Cách 4: Kế thừa nhiều model (Mixin) ===
class MyModel(models.Model):
    _name = 'my.model'
    _inherit = ['mail.thread', 'mail.activity.mixin']  # Kế thừa Discuss
    _description = 'My Model with Chatter'

    name = fields.Char(tracking=True)     # tracking=True để log thay đổi
```

### 4.3 Field Types

```python
from odoo import fields
from odoo.fields import Command

class MyModel(models.Model):
    _name = 'my.model'
    _description = 'My Model'

    # === Fields cơ bản ===
    name = fields.Char(string='Name', required=True, index=True)
    active = fields.Boolean(default=True)       # Nếu False → bản ghi bị ẩn (archived)
    sequence = fields.Integer(default=10)        # Thứ tự kéo thả
    description = fields.Text()
    html_content = fields.Html(sanitize=True)
    amount = fields.Float(digits=(16, 2))
    count = fields.Integer()
    price = fields.Monetary(currency_field='currency_id')
    currency_id = fields.Many2one('res.currency')
    date = fields.Date(default=fields.Date.today)
    datetime = fields.Datetime(default=fields.Datetime.now)
    image = fields.Image(max_width=1024, max_height=1024)
    file = fields.Binary(attachment=True)
    filename = fields.Char()

    # === Selection ===
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True)

    # === Relational fields ===
    # Many2one: FK đến bảng khác
    partner_id = fields.Many2one(
        'res.partner',
        string='Customer',
        required=True,
        ondelete='cascade',       # cascade / set null / restrict
        index=True,
        domain="[('is_company', '=', True)]",
        check_company=True,       # Kiểm tra multi-company
    )
    company_id = fields.Many2one(
        'res.company',
        default=lambda self: self.env.company,
    )

    # One2many: Inverse của Many2one
    line_ids = fields.One2many(
        'my.model.line',          # Model con
        'order_id',               # Many2one field ở model con trỏ về model này
        string='Order Lines',
    )

    # Many2many: Bảng trung gian
    tag_ids = fields.Many2many(
        'my.model.tag',
        'my_model_tag_rel',       # Tên bảng trung gian (optional)
        'model_id',               # Column FK model này
        'tag_id',                 # Column FK model kia
        string='Tags',
    )

    # === Computed fields ===
    total = fields.Float(
        compute='_compute_total',
        store=True,                # Lưu vào DB (cached)
        readonly=True,
    )
    display_name = fields.Char(compute='_compute_display_name')

    # === Related fields (shortcut) ===
    partner_email = fields.Char(
        related='partner_id.email',
        string='Email',
        readonly=True,
        store=True,               # Optional: lưu vào DB
    )
```

### 4.4 API Decorators

```python
from odoo import api, fields, models
from odoo.exceptions import ValidationError, UserError

class MyModel(models.Model):
    _name = 'my.model'
    _description = 'My Model'

    name = fields.Char(required=True)
    value = fields.Integer()
    total = fields.Float(compute='_compute_total', store=True)
    line_ids = fields.One2many('my.model.line', 'order_id')

    # --- @api.depends: Khai báo dependency cho computed field ---
    @api.depends('line_ids.price', 'line_ids.quantity')
    def _compute_total(self):
        for record in self:
            record.total = sum(
                line.price * line.quantity
                for line in record.line_ids
            )

    # --- @api.constrains: Validation khi lưu ---
    @api.constrains('value')
    def _check_value(self):
        for record in self:
            if record.value < 0:
                raise ValidationError("Value must be positive!")

    # --- @api.onchange: Trigger khi user thay đổi field trên UI ---
    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        if self.partner_id:
            self.name = self.partner_id.name

    # --- @api.model: Method cấp model (không cần recordset) ---
    @api.model
    def get_default_values(self):
        return {'value': 42}

    # --- @api.model_create_multi: Override create cho batch ---
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name'):
                vals['name'] = self.env['ir.sequence'].next_by_code('my.model')
        return super().create(vals_list)

    # --- Override write ---
    def write(self, vals):
        if 'state' in vals and vals['state'] == 'done':
            for record in self:
                if not record.line_ids:
                    raise UserError("Cannot confirm without lines!")
        return super().write(vals)

    # --- Override unlink (delete) ---
    def unlink(self):
        for record in self:
            if record.state == 'done':
                raise UserError("Cannot delete confirmed records!")
        return super().unlink()

    # --- @api.ondelete: Kiểm tra trước khi xóa ---
    @api.ondelete(at_uninstall=False)
    def _unlink_except_done(self):
        if any(record.state == 'done' for record in self):
            raise UserError("Cannot delete confirmed records!")
```

### 4.5 CRUD Operations & Recordset

```python
# === Environment (self.env) ===
env = self.env                          # Environment hiện tại
env.user                               # User hiện tại
env.company                            # Company hiện tại
env.context                            # Context dict
env.cr                                 # Database cursor
env.uid                                # User ID

# === Truy cập model ===
Partner = self.env['res.partner']

# === Search ===
partners = Partner.search([
    ('is_company', '=', True),
    ('country_id.code', '=', 'VN'),
], limit=10, order='name ASC')

count = Partner.search_count([('is_company', '=', True)])

# Đọc records
partners = Partner.search_read(
    domain=[('is_company', '=', True)],
    fields=['name', 'email', 'phone'],
    limit=10,
)

# === Create ===
partner = Partner.create({
    'name': 'Test Company',
    'is_company': True,
    'email': 'test@example.com',
})

# Batch create
partners = Partner.create([
    {'name': 'Partner 1'},
    {'name': 'Partner 2'},
])

# === Write (Update) ===
partner.write({'name': 'Updated Name'})
partner.name = 'Updated Name'            # Cũng được

# === Unlink (Delete) ===
partner.unlink()

# === Browse: Lấy recordset từ IDs ===
partner = Partner.browse(1)
partners = Partner.browse([1, 2, 3])

# === Ref: Lấy record từ XML ID ===
admin = self.env.ref('base.user_admin')

# === Recordset operations ===
all_records = recordset1 | recordset2    # Union
common = recordset1 & recordset2         # Intersection
diff = recordset1 - recordset2           # Difference
for record in recordset:                 # Iterate
    print(record.name)
recordset.filtered(lambda r: r.active)   # Filter
recordset.mapped('name')                 # Map field
recordset.sorted('name')                 # Sort

# === One2many/Many2many Commands (dùng trong create/write) ===
from odoo.fields import Command

record.write({
    'line_ids': [
        Command.create({'name': 'New Line'}),          # (0, 0, vals)
        Command.update(line_id, {'name': 'Updated'}),  # (1, id, vals)
        Command.delete(line_id),                        # (2, id, 0)
        Command.unlink(line_id),                        # (3, id, 0)
        Command.link(existing_id),                      # (4, id, 0)
        Command.clear(),                                # (5, 0, 0)
        Command.set([id1, id2]),                        # (6, 0, [ids])
    ]
})

# === Sudo: Bỏ qua access rules ===
partner = self.env['res.partner'].sudo().search([])

# === With context / With user ===
records = self.env['my.model'].with_context(lang='vi_VN').search([])
records = self.env['my.model'].with_user(other_user).search([])
```

### 4.6 Domain Expressions

```python
# Domain là list các tuple (field, operator, value)
domain = [
    ('name', '=', 'Test'),              # Bằng
    ('name', '!=', 'Test'),             # Khác
    ('name', 'like', 'Test%'),          # SQL LIKE
    ('name', 'ilike', 'test'),          # Case-insensitive LIKE
    ('amount', '>', 100),               # Lớn hơn
    ('amount', '>=', 100),              # Lớn hơn hoặc bằng
    ('amount', '<', 100),               # Nhỏ hơn
    ('amount', '<=', 100),              # Nhỏ hơn hoặc bằng
    ('state', 'in', ['draft', 'done']), # Trong danh sách
    ('state', 'not in', ['cancelled']), # Không trong danh sách
    ('parent_id', '=', False),          # IS NULL
    ('parent_id', '!=', False),         # IS NOT NULL
    ('child_ids', 'any', [              # Bất kỳ child nào thỏa mãn
        ('active', '=', True),
    ]),
]

# Operators logic: mặc định là AND
domain = [
    ('name', '=', 'A'),                 # AND ngầm định
    ('state', '=', 'done'),
]

# OR: dùng '|' prefix
domain = [
    '|',
    ('name', '=', 'A'),
    ('name', '=', 'B'),
]

# NOT: dùng '!' prefix
domain = [
    '!',
    ('active', '=', False),
]
```

---

## 5. Views & UI

### 5.1 Form View

```xml
<record model="ir.ui.view" id="my_model_view_form">
    <field name="name">my.model.form</field>
    <field name="model">my.model</field>
    <field name="arch" type="xml">
        <form string="My Model">
            <!-- Header: status bar & buttons -->
            <header>
                <button name="action_confirm" type="object"
                        string="Confirm" class="oe_highlight"
                        invisible="state != 'draft'"/>
                <button name="action_cancel" type="object"
                        string="Cancel"
                        invisible="state in ('done', 'cancelled')"/>
                <field name="state" widget="statusbar"
                       statusbar_visible="draft,confirmed,done"/>
            </header>

            <!-- Sheet: nội dung chính -->
            <sheet>
                <!-- Widget ảnh góc trên phải -->
                <field name="image_128" widget="image" class="oe_avatar"/>

                <!-- Tiêu đề -->
                <div class="oe_title">
                    <label for="name"/>
                    <h1><field name="name" placeholder="Enter name..."/></h1>
                </div>

                <!-- Nhóm fields -->
                <group>
                    <group string="General Information">
                        <field name="partner_id"/>
                        <field name="date"/>
                        <field name="amount"/>
                    </group>
                    <group string="Other">
                        <field name="company_id" groups="base.group_multi_company"/>
                        <field name="tag_ids" widget="many2many_tags"/>
                    </group>
                </group>

                <!-- Notebook (tabs) -->
                <notebook>
                    <page string="Lines" name="lines">
                        <field name="line_ids">
                            <list editable="bottom">
                                <field name="product_id"/>
                                <field name="quantity"/>
                                <field name="price"/>
                                <field name="subtotal"/>
                            </list>
                        </field>
                        <!-- Tổng cộng -->
                        <group class="oe_subtotal_footer">
                            <field name="total"/>
                        </group>
                    </page>
                    <page string="Notes" name="notes">
                        <field name="notes" placeholder="Add notes..."/>
                    </page>
                </notebook>
            </sheet>

            <!-- Chatter (messaging) - cần inherit mail.thread -->
            <chatter/>
        </form>
    </field>
</record>
```

### 5.2 List View

```xml
<record model="ir.ui.view" id="my_model_view_list">
    <field name="name">my.model.list</field>
    <field name="model">my.model</field>
    <field name="arch" type="xml">
        <list string="My Models"
              default_order="date desc"
              multi_edit="1"
              sample="1">
            <field name="name" decoration-bf="1"/>
            <field name="partner_id"/>
            <field name="date"/>
            <field name="amount" sum="Total Amount"/>
            <field name="state"
                   decoration-success="state == 'done'"
                   decoration-warning="state == 'draft'"
                   decoration-danger="state == 'cancelled'"
                   widget="badge"/>
        </list>
    </field>
</record>
```

### 5.3 Kanban View

```xml
<record model="ir.ui.view" id="my_model_view_kanban">
    <field name="name">my.model.kanban</field>
    <field name="model">my.model</field>
    <field name="arch" type="xml">
        <kanban default_group_by="state" class="o_kanban_small_column">
            <templates>
                <t t-name="card">
                    <field name="name" class="fw-bold fs-5"/>
                    <field name="partner_id"/>
                    <field name="amount" widget="monetary"/>
                    <field name="tag_ids" widget="many2many_tags"
                           options="{'color_field': 'color'}"/>
                </t>
            </templates>
        </kanban>
    </field>
</record>
```

### 5.4 Search View

```xml
<record model="ir.ui.view" id="my_model_view_search">
    <field name="name">my.model.search</field>
    <field name="model">my.model</field>
    <field name="arch" type="xml">
        <search string="Search My Models">
            <!-- Search fields -->
            <field name="name"/>
            <field name="partner_id"/>

            <!-- Predefined filters -->
            <filter name="filter_draft" string="Draft"
                    domain="[('state', '=', 'draft')]"/>
            <filter name="filter_done" string="Done"
                    domain="[('state', '=', 'done')]"/>
            <separator/>
            <filter name="filter_my" string="My Records"
                    domain="[('create_uid', '=', uid)]"/>

            <!-- Group by -->
            <group expand="0" string="Group By">
                <filter name="group_state" string="Status"
                        context="{'group_by': 'state'}"/>
                <filter name="group_partner" string="Customer"
                        context="{'group_by': 'partner_id'}"/>
                <filter name="group_date" string="Date"
                        context="{'group_by': 'date:month'}"/>
            </group>
        </search>
    </field>
</record>
```

### 5.5 Actions & Menus

```xml
<!-- Window Action -->
<record model="ir.actions.act_window" id="action_my_model">
    <field name="name">My Models</field>
    <field name="res_model">my.model</field>
    <field name="view_mode">list,form,kanban</field>
    <field name="context">{'search_default_filter_my': 1}</field>
    <field name="domain">[('active', '=', True)]</field>
    <field name="help" type="html">
        <p class="o_view_nocontent_smiling_face">
            Create your first record!
        </p>
    </field>
</record>

<!-- Menu items -->
<menuitem id="menu_my_module_root"
          name="My Module"
          sequence="10"
          web_icon="my_module,static/description/icon.png"/>

<menuitem id="menu_my_module_main"
          name="My Models"
          parent="menu_my_module_root"
          sequence="10"/>

<menuitem id="menu_my_model"
          name="All Records"
          parent="menu_my_module_main"
          action="action_my_model"
          sequence="10"/>
```

### 5.6 Mở rộng View có sẵn (Inheritance)

```xml
<!-- Thêm field vào form view của res.partner -->
<record model="ir.ui.view" id="res_partner_view_form_inherit">
    <field name="name">res.partner.form.inherit.my_module</field>
    <field name="model">res.partner</field>
    <field name="inherit_id" ref="base.view_partner_form"/>
    <field name="arch" type="xml">
        <!-- Thêm field sau field phone -->
        <field name="phone" position="after">
            <field name="my_custom_field"/>
        </field>

        <!-- Thêm page vào notebook -->
        <xpath expr="//notebook" position="inside">
            <page string="My Custom Tab">
                <field name="my_custom_ids"/>
            </page>
        </xpath>

        <!-- Thay thế element -->
        <field name="website" position="replace">
            <field name="website" widget="url" placeholder="https://..."/>
        </field>

        <!-- Ẩn element -->
        <field name="fax" position="attributes">
            <attribute name="invisible">1</attribute>
        </field>
    </field>
</record>
```

---

## 6. Security & Access Control

### 6.1 Groups (`security/security.xml`)

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <!-- Module category -->
    <record model="ir.module.category" id="module_category_my_module">
        <field name="name">My Module</field>
        <field name="sequence">100</field>
    </record>

    <!-- User group -->
    <record model="res.groups" id="group_my_module_user">
        <field name="name">User</field>
        <field name="category_id" ref="module_category_my_module"/>
        <field name="implied_ids" eval="[
            Command.link(ref('base.group_user')),
        ]"/>
    </record>

    <!-- Manager group (kế thừa User) -->
    <record model="res.groups" id="group_my_module_manager">
        <field name="name">Manager</field>
        <field name="category_id" ref="module_category_my_module"/>
        <field name="implied_ids" eval="[
            Command.link(ref('group_my_module_user')),
        ]"/>
        <field name="users" eval="[
            Command.link(ref('base.user_root')),
            Command.link(ref('base.user_admin')),
        ]"/>
    </record>
</odoo>
```

### 6.2 Access Control List (`security/ir.model.access.csv`)

```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_my_model_user,my.model.user,model_my_model,group_my_module_user,1,1,1,0
access_my_model_manager,my.model.manager,model_my_model,group_my_module_manager,1,1,1,1
access_my_model_line_user,my.model.line.user,model_my_model_line,group_my_module_user,1,1,1,1
```

Quy tắc đặt tên `model_id:id`:
- Model `my.model` → `model_my_model` (thay `.` bằng `_`)
- Model `my.model.line` → `model_my_model_line`

### 6.3 Record Rules (`security/security.xml`)

```xml
<!-- User chỉ thấy records của company mình -->
<record model="ir.rule" id="rule_my_model_company">
    <field name="name">My Model: multi-company</field>
    <field name="model_id" ref="model_my_model"/>
    <field name="domain_force">[
        ('company_id', 'in', company_ids)
    ]</field>
</record>

<!-- User chỉ thấy records của mình, manager thấy tất cả -->
<record model="ir.rule" id="rule_my_model_user">
    <field name="name">My Model: user sees own</field>
    <field name="model_id" ref="model_my_model"/>
    <field name="groups" eval="[
        Command.link(ref('group_my_module_user')),
    ]"/>
    <field name="domain_force">[
        ('create_uid', '=', user.id)
    ]</field>
</record>
```

### 6.4 Field-level access

```python
# Chỉ group manager mới thấy field này
secret_field = fields.Char(groups='my_module.group_my_module_manager')
```

```xml
<!-- Trong view: ẩn field theo group -->
<field name="secret_field" groups="my_module.group_my_module_manager"/>
```

---

## 7. Controllers (HTTP)

### 7.1 Controller cơ bản

```python
# controllers/main.py
from odoo import http
from odoo.http import request


class MyController(http.Controller):

    # === JSON-RPC endpoint (cho AJAX calls từ frontend) ===
    @http.route('/my_module/data', type='jsonrpc', auth='user')
    def get_data(self, **kwargs):
        records = request.env['my.model'].search_read(
            [], fields=['name', 'amount'], limit=10
        )
        return {'records': records}

    # === HTTP endpoint (trả về HTML) ===
    @http.route('/my_module/page', type='http', auth='public', website=True)
    def my_page(self, **kwargs):
        records = request.env['my.model'].sudo().search([])
        return request.render('my_module.my_page_template', {
            'records': records,
        })

    # === Download file ===
    @http.route('/my_module/download/<int:record_id>', type='http', auth='user')
    def download(self, record_id, **kwargs):
        record = request.env['my.model'].browse(record_id)
        if not record.exists():
            return request.not_found()
        return request.make_response(
            record.file_data,
            headers=[
                ('Content-Type', 'application/octet-stream'),
                ('Content-Disposition', f'attachment; filename="{record.filename}"'),
            ]
        )
```

### 7.2 Auth types

| Auth | Mô tả |
|------|--------|
| `auth='user'` | Phải đăng nhập (mặc định) |
| `auth='public'` | Truy cập public hoặc user đã đăng nhập |
| `auth='none'` | Không cần auth, không có env |

### 7.3 Route parameters

```python
@http.route(
    '/my/<string:name>/record/<int:record_id>',
    type='http',               # 'http' hoặc 'jsonrpc'
    auth='user',               # 'user', 'public', 'none'
    methods=['GET', 'POST'],   # HTTP methods cho phép
    website=True,              # Sử dụng website layout
    sitemap=True,              # Cho phép sitemap crawl
    csrf=True,                 # Bật CSRF protection (mặc định True)
    cors='*',                  # CORS headers
    readonly=True,             # Sử dụng read-only cursor
)
def my_route(self, name, record_id, **kwargs):
    pass
```

---

## 8. Data files & Demo

### 8.1 Data XML

```xml
<!-- data/data.xml -->
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <data noupdate="1">
        <!-- noupdate="1": không ghi đè khi update module -->

        <!-- Tạo record -->
        <record model="my.model.tag" id="tag_important">
            <field name="name">Important</field>
            <field name="color">1</field>
        </record>

        <!-- Tạo sequence -->
        <record model="ir.sequence" id="seq_my_model">
            <field name="name">My Model Sequence</field>
            <field name="code">my.model</field>
            <field name="prefix">MY/%(year)s/</field>
            <field name="padding">5</field>
        </record>

        <!-- Tạo cron job -->
        <record model="ir.cron" id="cron_my_cleanup">
            <field name="name">My Module: Cleanup Old Records</field>
            <field name="model_id" ref="model_my_model"/>
            <field name="state">code</field>
            <field name="code">model._cron_cleanup()</field>
            <field name="interval_number">1</field>
            <field name="interval_type">days</field>
            <field name="numbercall">-1</field>
        </record>

        <!-- Email template -->
        <record model="mail.template" id="email_template_my_model">
            <field name="name">My Model: Notification</field>
            <field name="model_id" ref="model_my_model"/>
            <field name="subject">{{ object.name }} - Notification</field>
            <field name="email_from">{{ (object.company_id.email or user.email) }}</field>
            <field name="email_to">{{ object.partner_id.email }}</field>
            <field name="body_html" type="html">
                <p>Dear {{ object.partner_id.name }},</p>
                <p>Your record <strong>{{ object.name }}</strong> has been confirmed.</p>
            </field>
        </record>
    </data>
</odoo>
```

### 8.2 Demo data

```xml
<!-- demo/demo.xml -->
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <data>
        <record model="my.model" id="demo_record_1">
            <field name="name">Demo Record 1</field>
            <field name="partner_id" ref="base.res_partner_1"/>
            <field name="amount">1500.00</field>
            <field name="date">2025-01-15</field>
            <field name="state">confirmed</field>
        </record>
    </data>
</odoo>
```

### 8.3 CSV data

```csv
"id","name","code","active"
"my_module.record_1","Record 1","R001",1
"my_module.record_2","Record 2","R002",1
```

---

## 9. Wizards (TransientModel)

Wizards dùng cho các hành động tạm thời (popup form).

### 9.1 Model

```python
# wizards/my_wizard.py
from odoo import models, fields, api

class MyWizard(models.TransientModel):
    _name = 'my.module.wizard'
    _description = 'My Wizard'

    date_from = fields.Date(required=True, default=fields.Date.today)
    date_to = fields.Date(required=True)
    partner_ids = fields.Many2many('res.partner', string='Partners')
    note = fields.Text()

    def action_confirm(self):
        """Xử lý khi user bấm Confirm"""
        self.ensure_one()

        # Lấy active records từ context (nếu wizard mở từ list view)
        active_ids = self.env.context.get('active_ids', [])
        records = self.env['my.model'].browse(active_ids)

        # Xử lý business logic
        for record in records:
            record.write({
                'date': self.date_from,
                'partner_id': self.partner_ids[0].id if self.partner_ids else False,
            })

        # Trả về action (hoặc đóng wizard)
        return {'type': 'ir.actions.act_window_close'}

        # Hoặc trả về action mở view khác
        # return {
        #     'type': 'ir.actions.act_window',
        #     'res_model': 'my.model',
        #     'view_mode': 'list',
        #     'target': 'current',
        # }
```

### 9.2 View

```xml
<!-- wizards/my_wizard_views.xml -->
<record model="ir.ui.view" id="my_wizard_view_form">
    <field name="name">my.module.wizard.form</field>
    <field name="model">my.module.wizard</field>
    <field name="arch" type="xml">
        <form string="My Wizard">
            <group>
                <field name="date_from"/>
                <field name="date_to"/>
                <field name="partner_ids" widget="many2many_tags"/>
            </group>
            <field name="note"/>
            <footer>
                <button name="action_confirm" type="object"
                        string="Confirm" class="btn-primary"/>
                <button string="Cancel" class="btn-secondary" special="cancel"/>
            </footer>
        </form>
    </field>
</record>

<!-- Action để mở wizard -->
<record model="ir.actions.act_window" id="action_my_wizard">
    <field name="name">My Wizard</field>
    <field name="res_model">my.module.wizard</field>
    <field name="view_mode">form</field>
    <field name="target">new</field>
    <field name="binding_model_id" ref="model_my_model"/>
    <field name="binding_view_types">list,form</field>
</record>
```

---

## 10. Frontend (OWL/JS)

### 10.1 OWL Component

```javascript
// static/src/components/my_component.js
import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class MyComponent extends Component {
    static template = "my_module.MyComponent";
    static props = {
        record: { type: Object },
        title: { type: String, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({
            count: 0,
            loading: false,
        });
    }

    async onButtonClick() {
        this.state.loading = true;
        try {
            const result = await this.orm.call(
                "my.model",
                "my_method",
                [this.props.record.resId],
            );
            this.state.count = result;
            this.notification.add("Success!", { type: "success" });
        } catch (error) {
            this.notification.add("Error!", { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }
}
```

### 10.2 OWL Template (XML)

```xml
<!-- static/src/components/my_component.xml -->
<?xml version="1.0" encoding="UTF-8"?>
<templates xml:space="preserve">
    <t t-name="my_module.MyComponent">
        <div class="my_component">
            <h3 t-if="props.title" t-esc="props.title"/>
            <p>Count: <t t-esc="state.count"/></p>
            <button class="btn btn-primary"
                    t-on-click="onButtonClick"
                    t-att-disabled="state.loading">
                <t t-if="state.loading">Loading...</t>
                <t t-else="">Click me</t>
            </button>
        </div>
    </t>
</templates>
```

### 10.3 Đăng ký vào Registry

```javascript
// Đăng ký component vào action registry
import { registry } from "@web/core/registry";
registry.category("actions").add("my_module.my_action", MyComponent);

// Đăng ký vào systray (top-right icons)
registry.category("systray").add("my_module.MySystray", {
    Component: MySystrayComponent,
    isDisplayed: (env) => true,
});

// Đăng ký field widget
registry.category("fields").add("my_widget", {
    component: MyFieldWidget,
    supportedTypes: ["char", "text"],
});
```

---

## 11. Reports

### 11.1 Report Action

```xml
<!-- report/report_actions.xml -->
<record model="ir.actions.report" id="action_report_my_model">
    <field name="name">My Model Report</field>
    <field name="model">my.model</field>
    <field name="report_type">qweb-pdf</field>
    <field name="report_name">my_module.report_my_model_template</field>
    <field name="report_file">my_module.report_my_model_template</field>
    <field name="binding_model_id" ref="model_my_model"/>
    <field name="binding_type">report</field>
    <field name="paperformat_id" ref="base.paperformat_euro"/>
</record>
```

### 11.2 Report Template (QWeb)

```xml
<!-- report/report_templates.xml -->
<template id="report_my_model_template">
    <t t-call="web.html_container">
        <t t-foreach="docs" t-as="doc">
            <t t-call="web.external_layout">
                <div class="page">
                    <h2><t t-esc="doc.name"/></h2>

                    <div class="row mt-4">
                        <div class="col-6">
                            <strong>Customer:</strong>
                            <span t-field="doc.partner_id"/>
                        </div>
                        <div class="col-6">
                            <strong>Date:</strong>
                            <span t-field="doc.date"/>
                        </div>
                    </div>

                    <table class="table table-sm mt-4">
                        <thead>
                            <tr>
                                <th>Product</th>
                                <th class="text-end">Qty</th>
                                <th class="text-end">Price</th>
                                <th class="text-end">Subtotal</th>
                            </tr>
                        </thead>
                        <tbody>
                            <t t-foreach="doc.line_ids" t-as="line">
                                <tr>
                                    <td><t t-esc="line.product_id.name"/></td>
                                    <td class="text-end">
                                        <t t-esc="line.quantity"/>
                                    </td>
                                    <td class="text-end">
                                        <t t-esc="line.price"
                                           t-options="{'widget': 'monetary', 'display_currency': doc.currency_id}"/>
                                    </td>
                                    <td class="text-end">
                                        <t t-esc="line.subtotal"
                                           t-options="{'widget': 'monetary', 'display_currency': doc.currency_id}"/>
                                    </td>
                                </tr>
                            </t>
                        </tbody>
                        <tfoot>
                            <tr>
                                <td colspan="3" class="text-end"><strong>Total:</strong></td>
                                <td class="text-end">
                                    <strong t-field="doc.total"
                                            t-options="{'widget': 'monetary', 'display_currency': doc.currency_id}"/>
                                </td>
                            </tr>
                        </tfoot>
                    </table>
                </div>
            </t>
        </t>
    </t>
</template>
```

---

## 12. Testing

### 12.1 Test Classes

| Class | Mô tả |
|-------|--------|
| `TransactionCase` | Mỗi test method chạy trong savepoint, rollback sau khi xong. Dùng cho phần lớn test. |
| `SingleTransactionCase` | Tất cả test methods chia sẻ 1 transaction. Dùng khi test phụ thuộc nhau. |
| `HttpCase` | Test HTTP endpoints, tour tests. Kế thừa từ TransactionCase. |

### 12.2 Viết Test

```python
# tests/__init__.py
from . import test_my_model
from . import test_access_rights

# tests/test_my_model.py
from odoo.tests import common, tagged, new_test_user
from odoo.exceptions import ValidationError, UserError, AccessError


@tagged('post_install', '-at_install')   # Chạy sau khi install tất cả modules
class TestMyModel(common.TransactionCase):

    @classmethod
    def setUpClass(cls):
        """Setup dữ liệu dùng chung cho tất cả test methods"""
        super().setUpClass()

        # Tạo test users
        cls.manager = new_test_user(
            cls.env, 'test_manager',
            groups='my_module.group_my_module_manager,base.group_partner_manager',
        )
        cls.user = new_test_user(
            cls.env, 'test_user',
            groups='my_module.group_my_module_user',
        )

        # Tạo test data
        cls.partner = cls.env['res.partner'].create({
            'name': 'Test Partner',
            'email': 'test@example.com',
        })
        cls.record = cls.env['my.model'].create({
            'name': 'Test Record',
            'partner_id': cls.partner.id,
            'amount': 1000,
        })

    def test_create_record(self):
        """Test tạo record mới"""
        record = self.env['my.model'].create({
            'name': 'New Record',
            'partner_id': self.partner.id,
        })
        self.assertTrue(record.id)
        self.assertEqual(record.state, 'draft')

    def test_confirm_record(self):
        """Test xác nhận record"""
        self.record.action_confirm()
        self.assertEqual(self.record.state, 'confirmed')

    def test_constraint_negative_value(self):
        """Test constraint: value phải >= 0"""
        with self.assertRaises(ValidationError):
            self.record.write({'value': -1})

    def test_cannot_delete_confirmed(self):
        """Test không thể xóa record đã confirmed"""
        self.record.action_confirm()
        with self.assertRaises(UserError):
            self.record.unlink()

    def test_computed_total(self):
        """Test computed field total"""
        self.env['my.model.line'].create([
            {'order_id': self.record.id, 'price': 100, 'quantity': 2},
            {'order_id': self.record.id, 'price': 200, 'quantity': 1},
        ])
        self.assertEqual(self.record.total, 400)  # 100*2 + 200*1

    def test_access_rights_user(self):
        """Test user không thể xóa records"""
        with self.assertRaises(AccessError):
            self.record.with_user(self.user).unlink()

    def test_access_rights_manager(self):
        """Test manager có thể xóa records"""
        self.record.with_user(self.manager).unlink()
        self.assertFalse(self.record.exists())
```

### 12.3 HTTP / Tour Tests

```python
from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestMyModuleUI(HttpCase):

    def test_my_module_tour(self):
        """Test UI tour"""
        self.start_tour(
            '/odoo/my-module',         # URL bắt đầu
            'my_module_tour',          # Tên tour
            login='admin',             # User login
        )
```

```javascript
// static/tests/my_module_tour.js
import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("my_module_tour", {
    url: "/odoo/my-module",
    steps: () => [
        {
            trigger: ".o_list_button_add",
            content: "Click to create new record",
            run: "click",
        },
        {
            trigger: ".o_field_widget[name='name'] input",
            content: "Enter name",
            run: "edit Test Record",
        },
        {
            trigger: ".o_form_button_save",
            content: "Save the record",
            run: "click",
        },
    ],
});
```

### 12.4 Tags phổ biến

| Tag | Mô tả |
|-----|--------|
| `at_install` | Chạy ngay sau khi cài module (mặc định) |
| `post_install` | Chạy sau khi tất cả modules đã cài xong |
| `standard` | Test tiêu chuẩn (mặc định) |
| `-at_install` | Loại bỏ tag `at_install` |

### 12.5 Chạy Tests

```bash
# Chạy tất cả tests của 1 module
python odoo-bin -d testdb --test-enable --test-tags=/my_module --stop-after-init

# Chạy test class cụ thể
python odoo-bin -d testdb --test-enable --test-tags=/my_module:TestMyModel --stop-after-init

# Chạy tests theo tag
python odoo-bin -d testdb --test-enable --test-tags=post_install --stop-after-init

# Chạy với log chi tiết
python odoo-bin -d testdb --test-enable --test-tags=/my_module \
    --log-level=test --stop-after-init
```

---

## 13. Migration & Upgrade

### 13.1 Cấu trúc migration scripts

Khi thay đổi version trong `__manifest__.py`, Odoo sẽ chạy migration scripts tương ứng.

```
my_module/
└── migrations/
    ├── 19.0.1.1.0/               # Version mới
    │   ├── pre-migrate.py        # Chạy TRƯỚC update module
    │   ├── post-migrate.py       # Chạy SAU update module
    │   └── end-migrate.py        # Chạy sau TẤT CẢ modules update xong
    ├── 19.0.2.0.0/
    │   └── pre-migrate.py
    └── 0.0.0/                    # Chạy trên MỌI version change
        └── end-invariants.py
```

### 13.2 Migration Script

```python
# migrations/19.0.1.1.0/pre-migrate.py
import logging
from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

def migrate(cr, installed_version):
    """
    Pre-migration: chạy trước khi module được update.
    Dùng cho: đổi tên cột, thêm cột tạm, backup data, ...

    Args:
        cr: Database cursor (raw SQL)
        installed_version: Version hiện tại đang cài
    """
    _logger.info("Pre-migrating my_module from %s", installed_version)

    # Đổi tên cột
    cr.execute("""
        ALTER TABLE my_model
        RENAME COLUMN old_field TO new_field
    """)

    # Thêm cột mới với giá trị mặc định
    cr.execute("""
        ALTER TABLE my_model
        ADD COLUMN IF NOT EXISTS new_column VARCHAR DEFAULT 'draft'
    """)
```

```python
# migrations/19.0.1.1.0/post-migrate.py
import logging
from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

def migrate(cr, installed_version):
    """
    Post-migration: chạy sau khi module được update.
    Dùng cho: migrate data, tính lại computed fields, ...
    Lúc này ORM đã sẵn sàng.
    """
    _logger.info("Post-migrating my_module from %s", installed_version)

    env = api.Environment(cr, SUPERUSER_ID, {})

    # Migrate data sử dụng ORM
    records = env['my.model'].search([('old_state', '!=', False)])
    for record in records:
        record.write({
            'new_state': record.old_state,
        })

    # Hoặc migrate bằng SQL thuần (nhanh hơn cho data lớn)
    cr.execute("""
        UPDATE my_model
        SET new_state = old_state
        WHERE old_state IS NOT NULL
    """)
```

### 13.3 Module Lifecycle

```
Uninstalled → Installing → Installed → Upgrading → Installed
                                     → Uninstalling → Uninstalled
```

Khi **upgrade** (`-u my_module`):

1. `pre-migrate.py` scripts chạy (raw SQL, chưa có ORM mới)
2. Module code được load lại (models, views, data)
3. Database schema được update (thêm/sửa cột)
4. Data files được re-load
5. `post-migrate.py` scripts chạy (ORM mới đã sẵn sàng)
6. Sau khi TẤT CẢ modules upgrade xong → `end-migrate.py` chạy

---

## 14. Deploy

### 14.1 Cấu hình Production

```ini
# odoo.conf - Production
[options]
; Database
db_host = localhost
db_port = 5432
db_user = odoo
db_password = strong_password
db_name = production_db
db_maxconn = 64
db_template = template0

; Server
http_port = 8069
proxy_mode = True               ; Chạy sau reverse proxy (Nginx)
workers = 4                     ; Số worker processes (= CPU cores * 2)
max_cron_threads = 2
limit_memory_hard = 2684354560  ; 2.5 GB
limit_memory_soft = 2147483648  ; 2 GB
limit_time_cpu = 600
limit_time_real = 1200
limit_time_real_cron = -1
limit_request = 65536

; Security
list_db = False                 ; Không hiển thị danh sách database
admin_passwd = strong_master_password

; Logging
log_level = warn
logfile = /var/log/odoo/odoo.log
logrotate = True

; Performance
data_dir = /var/lib/odoo
```

### 14.2 Nginx Reverse Proxy

```nginx
upstream odoo {
    server 127.0.0.1:8069;
}
upstream odoo-websocket {
    server 127.0.0.1:8072;
}

server {
    listen 443 ssl http2;
    server_name odoo.mycompany.com;

    ssl_certificate     /etc/ssl/certs/odoo.crt;
    ssl_certificate_key /etc/ssl/private/odoo.key;

    access_log /var/log/nginx/odoo-access.log;
    error_log  /var/log/nginx/odoo-error.log;

    proxy_buffers 16 64k;
    proxy_buffer_size 128k;
    proxy_read_timeout 900s;
    proxy_connect_timeout 900s;
    proxy_send_timeout 900s;

    client_max_body_size 200m;

    location / {
        proxy_pass http://odoo;
        proxy_set_header X-Forwarded-Host $http_host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_redirect off;
    }

    location /websocket {
        proxy_pass http://odoo-websocket;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "Upgrade";
        proxy_set_header X-Forwarded-Host $http_host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 86400;
    }

    location ~* /web/static/ {
        proxy_cache_valid 200 90m;
        proxy_buffering on;
        expires 864000;
        proxy_pass http://odoo;
    }

    gzip on;
    gzip_types text/css text/plain text/xml application/xml application/javascript application/json;
}
```

### 14.3 Systemd Service

```ini
# /etc/systemd/system/odoo.service
[Unit]
Description=Odoo 19.0
After=network.target postgresql.service

[Service]
Type=simple
User=odoo
Group=odoo
ExecStart=/opt/odoo/venv/bin/python /opt/odoo/odoo-bin -c /etc/odoo/odoo.conf
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
# Quản lý service
sudo systemctl start odoo
sudo systemctl stop odoo
sudo systemctl restart odoo
sudo systemctl enable odoo      # Auto-start khi boot
```

### 14.4 Deploy Module mới

```bash
# 1. Copy module vào addons path
cp -r my_module /opt/odoo/custom_addons/

# 2. Cập nhật module list
python odoo-bin -d production_db --update=base --stop-after-init

# 3. Cài đặt module mới
python odoo-bin -d production_db -i my_module --stop-after-init

# 4. Hoặc update module đã cài
python odoo-bin -d production_db -u my_module --stop-after-init

# 5. Restart service
sudo systemctl restart odoo
```

### 14.5 Docker Deployment

```yaml
# docker-compose.yml
version: '3.8'

services:
  odoo:
    image: odoo:19.0
    ports:
      - "8069:8069"
      - "8072:8072"
    volumes:
      - ./custom_addons:/mnt/extra-addons
      - ./config/odoo.conf:/etc/odoo/odoo.conf
      - odoo-data:/var/lib/odoo
    depends_on:
      - db
    environment:
      - HOST=db
      - USER=odoo
      - PASSWORD=odoo

  db:
    image: postgres:15
    environment:
      - POSTGRES_USER=odoo
      - POSTGRES_PASSWORD=odoo
      - POSTGRES_DB=postgres
    volumes:
      - pg-data:/var/lib/postgresql/data

volumes:
  odoo-data:
  pg-data:
```

---

## 15. Best Practices

### 15.1 Naming Conventions

| Loại | Convention | Ví dụ |
|------|-----------|-------|
| Module name | `snake_case` | `my_custom_module` |
| Model name | `dot.separated` | `my.module.model` |
| Field name | `snake_case` | `partner_id`, `total_amount` |
| Method name | `snake_case` | `action_confirm`, `_compute_total` |
| View XML ID | `module.model_view_type` | `my_module.my_model_view_form` |
| Security group | `module.group_*` | `my_module.group_my_module_manager` |
| Menu XML ID | `module.menu_*` | `my_module.menu_my_model` |
| Private method | `_prefix` | `_compute_total`, `_check_value` |
| Action method | `action_*` | `action_confirm`, `action_cancel` |
| Cron method | `_cron_*` | `_cron_cleanup` |

### 15.2 Coding Standards

```python
# 1. Import order
from odoo import api, fields, models, _    # Odoo core
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare

# 2. Luôn sử dụng _() cho chuỗi cần dịch
raise UserError(_("Cannot delete a confirmed record."))

# 3. Dùng self.ensure_one() khi method chỉ chạy trên 1 record
def action_confirm(self):
    self.ensure_one()
    self.state = 'confirmed'

# 4. Batch operations - xử lý nhiều records cùng lúc
@api.model_create_multi
def create(self, vals_list):
    # Xử lý batch thay vì từng record
    return super().create(vals_list)

# 5. Sử dụng sudo() cẩn thận
record = self.env['my.model'].sudo().search([])  # Bypass access rights

# 6. Tránh SQL injection - dùng parameterized queries
self.env.cr.execute("SELECT id FROM my_table WHERE name = %s", [name])
# KHÔNG: self.env.cr.execute(f"SELECT id FROM my_table WHERE name = '{name}'")

# 7. Log đúng cách
import logging
_logger = logging.getLogger(__name__)
_logger.info("Processing %d records", len(records))
_logger.warning("Unexpected state: %s", record.state)
_logger.error("Failed to process record %s: %s", record.id, error)
```

### 15.3 Performance Tips

```python
# 1. Tránh N+1 queries - dùng prefetch
for record in self:
    # BAD: mỗi lần truy cập partner_id tạo 1 query
    # Odoo tự prefetch nếu dùng recordset đúng cách
    print(record.partner_id.name)

# 2. Dùng search_read thay vì search + read
data = self.env['res.partner'].search_read(
    [('active', '=', True)],
    fields=['name', 'email'],
    limit=100,
)

# 3. Dùng with_context(prefetch_fields=False) khi chỉ cần vài field
records = self.env['large.model'].with_context(
    prefetch_fields=False
).search([])

# 4. Bulk write thay vì loop write
# BAD
for record in records:
    record.write({'state': 'done'})

# GOOD
records.write({'state': 'done'})

# 5. Dùng SQL cho xử lý data lớn
self.env.cr.execute("""
    UPDATE my_table
    SET state = 'done'
    WHERE state = 'draft' AND date < %s
""", [cutoff_date])
self.env['my.model'].invalidate_model(['state'])

# 6. Store computed fields khi cần truy vấn/filter
total = fields.Float(compute='_compute_total', store=True)

# 7. Sử dụng @ormcache cho cache
from odoo.tools import ormcache

@ormcache('self.env.uid', 'key')
def _get_cached_value(self, key):
    return expensive_computation(key)
```

### 15.4 Checklist trước khi deploy

- [ ] Tất cả models có `_description`
- [ ] Security: `ir.model.access.csv` cho mọi model
- [ ] Security: Record rules cho multi-company (nếu cần)
- [ ] Tests: Coverage cho business logic chính
- [ ] Tests: Chạy pass trên database sạch
- [ ] i18n: Strings user-facing dùng `_()`
- [ ] Migration: Scripts cho thay đổi breaking
- [ ] `__manifest__.py`: Version đúng, dependencies đầy đủ
- [ ] `__manifest__.py`: `data` files theo đúng thứ tự (security trước views)
- [ ] Không có `print()` statements
- [ ] Logging: Sử dụng `_logger` thay vì `print`
- [ ] SQL: Không có SQL injection risks
- [ ] Performance: Không có N+1 query patterns

---

*Tài liệu được tạo từ codebase Odoo 19.0 - Branch `19.0`*
