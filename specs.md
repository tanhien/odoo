# Odoo 19.0 - System Specification

## 1. Tổng quan hệ thống

**Odoo** là một hệ thống ERP (Enterprise Resource Planning) và CRM mã nguồn mở toàn diện, được phát triển bởi Odoo S.A. (trước đây là OpenERP S.A.). Hệ thống cung cấp giải pháp quản lý doanh nghiệp tích hợp bao gồm kế toán, quản lý kho, bán hàng, mua hàng, sản xuất, CRM, quản lý nhân sự, website, POS và nhiều module khác.

- **Phiên bản**: 19.0 (Production/Stable)
- **Giấy phép**: LGPL-3
- **Ngôn ngữ chính**: Python (backend), JavaScript/OWL (frontend)
- **Cơ sở dữ liệu**: PostgreSQL (tối thiểu v13)
- **Python hỗ trợ**: 3.10 - 3.13
- **Website**: https://www.odoo.com

---

## 2. Kiến trúc tổng thể

### 2.1 Mô hình kiến trúc

Odoo sử dụng kiến trúc **3-tier** (3 tầng):

```
┌─────────────────────────────────────────────────┐
│              Presentation Layer                  │
│   (OWL Framework - SPA Web Client, Website)     │
├─────────────────────────────────────────────────┤
│              Business Logic Layer                │
│   (Python ORM, Controllers, Services)            │
├─────────────────────────────────────────────────┤
│              Data Layer                          │
│   (PostgreSQL Database)                          │
└─────────────────────────────────────────────────┘
```

### 2.2 Cấu trúc thư mục gốc

```
odoo/
├── odoo-bin              # Entry point - khởi chạy server
├── odoo/                 # Core framework
│   ├── cli/              # CLI commands (server, shell, scaffold, ...)
│   ├── orm/              # Object-Relational Mapping
│   ├── modules/          # Module loading & registry
│   ├── service/          # Server services (HTTP, RPC, DB)
│   ├── tools/            # Tiện ích hệ thống
│   ├── http.py           # WSGI HTTP layer
│   ├── sql_db.py         # PostgreSQL connector
│   ├── exceptions.py     # Custom exceptions
│   ├── release.py        # Thông tin phiên bản
│   └── addons/base/      # Module base (kernel)
├── addons/               # 612 addon modules
├── setup/                # Setup & packaging
└── requirements.txt      # Python dependencies
```

---

## 3. Core Framework (`odoo/`)

### 3.1 Entry Point (`odoo-bin`)

File khởi chạy chính, gọi `odoo.cli.main()` để parse command và khởi động server.

### 3.2 CLI Commands (`odoo/cli/`)

| File | Lệnh | Mô tả |
|------|-------|--------|
| `server.py` | `server` | Khởi động Odoo server (lệnh mặc định) |
| `shell.py` | `shell` | Interactive Python shell với ORM |
| `scaffold.py` | `scaffold` | Tạo skeleton cho module mới |
| `db.py` | `db` | Quản lý database (create, drop, backup, restore) |
| `deploy.py` | `deploy` | Deploy module lên remote server |
| `cloc.py` | `cloc` | Đếm dòng code |
| `populate.py` | `populate` | Tạo dữ liệu test |
| `i18n.py` | `i18n` | Quản lý bản dịch |
| `neutralize.py` | `neutralize` | Vô hiệu hóa database cho môi trường test |
| `upgrade_code.py` | `upgrade_code` | Chạy migration scripts |

### 3.3 ORM - Object Relational Mapping (`odoo/orm/`)

ORM là trung tâm của Odoo, cung cấp lớp trừu tượng trên PostgreSQL.

#### Các file chính:

| File | Mô tả |
|------|--------|
| `models.py` | BaseModel - lớp cha của mọi model |
| `model_classes.py` | Định nghĩa các loại model (Model, TransientModel, AbstractModel) |
| `models_transient.py` | TransientModel - model tạm thời tự xóa |
| `fields.py` | Lớp Field cơ sở |
| `fields_numeric.py` | Integer, Float, Monetary |
| `fields_textual.py` | Char, Text, Html |
| `fields_temporal.py` | Date, Datetime |
| `fields_binary.py` | Binary, Image |
| `fields_relational.py` | Many2one, One2many, Many2many |
| `fields_selection.py` | Selection |
| `fields_reference.py` | Reference |
| `fields_properties.py` | Properties (dynamic JSON fields) |
| `fields_misc.py` | Id, Boolean |
| `decorators.py` | API decorators (@api.depends, @api.constrains, ...) |
| `domains.py` | Domain expressions cho truy vấn |
| `environments.py` | Environment (env) - chứa cr, uid, context |
| `registry.py` | Registry - quản lý model registry |
| `commands.py` | CRUD commands |
| `identifiers.py` | NewId cho bản ghi chưa lưu |
| `utils.py` | Constants (SUPERUSER_ID), helper functions |

#### Đặc điểm ORM:

- **Hierarchical structure**: Hỗ trợ cấu trúc cây (parent/child)
- **Multi-level caching**: Hệ thống cache nhiều tầng
- **2 cơ chế kế thừa**: Classical inheritance và Delegation inheritance
- **Constraint validation**: Kiểm tra ràng buộc và validation
- **Field types phong phú**: varchar, integer, boolean, one2many, many2one, many2many, functional fields
- **Persistent storage**: PostgreSQL
- **Optimised queries**: Xử lý batch, prefetching

#### API Decorators (`odoo/orm/decorators.py`):

```python
@api.depends('field1', 'field2')     # Khai báo dependency cho computed field
@api.constrains('field1', 'field2')  # Khai báo constraint checker
@api.onchange('field1')              # Trigger khi field thay đổi (UI)
@api.ondelete(at_uninstall=False)    # Kiểm tra trước khi xóa record
@api.model                           # Method không cần recordset
@api.autovacuum                      # Tự động chạy dọn dẹp
```

### 3.4 HTTP Layer (`odoo/http.py`)

Odoo sử dụng **Werkzeug** làm WSGI framework. Luồng xử lý request:

```
Application.__call__ (WSGI entry)
├── Static files → Request._serve_static
├── No database  → Request._serve_nodb (auth='none' routes)
└── With database → Request._serve_db
    ├── ir.http._match → tìm route
    ├── ir.http._authenticate → xác thực user
    ├── ir.http._pre_dispatch → pre-processing
    ├── Dispatcher.dispatch → gọi endpoint controller
    └── ir.http._post_dispatch → post-processing
```

**Controller Pattern:**
```python
from odoo import http

class MyController(http.Controller):
    @http.route('/my/path', auth='user', type='json')
    def my_endpoint(self):
        return {...}
```

### 3.5 Database Layer (`odoo/sql_db.py`)

- **PostgreSQL connector** qua `psycopg2`
- Không phải database abstraction - đó là công việc của ORM
- Quản lý connection pooling
- Hỗ trợ read-only cursor và read/write cursor
- Hỗ trợ database replica (`db_replica_host`, `db_replica_port`)
- Auto-convert Decimal → Float

### 3.6 Server Architecture (`odoo/service/server.py`)

Odoo hỗ trợ **3 chế độ server**:

| Mode | Mô tả |
|------|--------|
| **Threaded** | Server đa luồng (mặc định trên Windows) |
| **Gevent** | Server bất đồng bộ dựa trên greenlet |
| **Prefork** | Server đa tiến trình (production trên Linux) |

Hỗ trợ hot-reload qua `inotify` (Linux) hoặc `watchdog`.

### 3.7 Services (`odoo/service/`)

| File | Mô tả |
|------|--------|
| `server.py` | Khởi động và quản lý server |
| `db.py` | Tạo, xóa, backup, restore database |
| `model.py` | RPC dispatch tới ORM model methods |
| `security.py` | Xác thực và phân quyền |
| `common.py` | Thông tin server (version, login, ...) |

### 3.8 Tools & Utilities (`odoo/tools/`)

| File | Mô tả |
|------|--------|
| `config.py` | Quản lý cấu hình hệ thống |
| `cache.py` | ORM cache (`@ormcache`) |
| `safe_eval.py` | Đánh giá biểu thức Python an toàn |
| `translate.py` | Hệ thống đa ngôn ngữ (i18n) |
| `mail.py` | Tiện ích email |
| `image.py` | Xử lý ảnh (resize, crop, ...) |
| `pdf/` | Xử lý PDF |
| `convert.py` | Convert XML/CSV data files |
| `query.py` | SQL query builder |
| `sql.py` | SQL utilities & helpers |
| `json.py` | JSON serialization |
| `barcode.py` | Tạo barcode |
| `float_utils.py` | Xử lý số thực chính xác |
| `date_utils.py` | Tiện ích ngày tháng |
| `rendering_tools.py` | Template rendering |
| `js_transpiler.py` | Transpile ES modules |
| `sourcemap_generator.py` | Tạo source maps cho JS |
| `profiler.py` | Profiling hệ thống |
| `view_validation.py` | Validate XML views |
| `template_inheritance.py` | Kế thừa template XML |
| `xml_utils.py` | Xử lý XML |

### 3.9 Module System (`odoo/modules/`)

| File | Mô tả |
|------|--------|
| `module.py` | Load module metadata, addons paths |
| `module_graph.py` | Xây dựng dependency graph |
| `loading.py` | Load và install modules |
| `migration.py` | Chạy migration scripts (pre/post/end) |
| `db.py` | Module state trong database |
| `registry/` | Module registry management |
| `neutralize.py` | Neutralize database |

### 3.10 Migration System (`odoo/upgrade_code/`)

Hệ thống migration tự động với các script chuyển đổi code giữa các phiên bản:

- `17.5-00-example.py` - Ví dụ migration
- `17.5-01-tree-to-list.py` - Đổi tree view → list view
- `18.1-00-sql-constraint.py` - Chuyển đổi SQL constraints
- `18.1-02-route-jsonrpc.py` - Chuyển đổi JSON-RPC routes
- `18.5-00-deprecated-properties.py` - Xử lý deprecated properties

---

## 4. Base Module (`odoo/addons/base/`)

Module **base** là kernel của Odoo, được cài đặt tự động trong mọi database.

### 4.1 IR Models (Information Repository)

| Model | Mô tả |
|-------|--------|
| `ir.model` | Metadata của tất cả models |
| `ir.model.fields` | Metadata các fields |
| `ir.model.data` | External identifiers (XML IDs) |
| `ir.actions` | Định nghĩa actions (window, server, report, ...) |
| `ir.actions.report` | Quản lý báo cáo |
| `ir.ui.view` | View definitions (XML) |
| `ir.ui.menu` | Menu items |
| `ir.rule` | Record-level access rules |
| `ir.config_parameter` | System parameters (key-value) |
| `ir.cron` | Scheduled actions (cron jobs) |
| `ir.sequence` | Auto-numbering sequences |
| `ir.attachment` | File attachments |
| `ir.mail_server` | Outgoing mail servers |
| `ir.filters` | Saved search filters |
| `ir.module.module` | Installed/available modules |
| `ir.asset` | Web asset bundles |
| `ir.http` | HTTP routing & middleware |
| `ir.qweb` | QWeb template engine |
| `ir.logging` | System logs |
| `ir.default` | Default field values |
| `ir.profile` | Profiling data |

### 4.2 Res Models (Resources)

| Model | Mô tả |
|-------|--------|
| `res.users` | Người dùng hệ thống |
| `res.groups` | Nhóm quyền |
| `res.company` | Công ty (multi-company support) |
| `res.partner` | Đối tác (khách hàng, nhà cung cấp, liên hệ) |
| `res.currency` | Tiền tệ & tỷ giá |
| `res.country` | Quốc gia & bang/tỉnh |
| `res.lang` | Ngôn ngữ |
| `res.bank` | Ngân hàng |
| `res.config` | Configuration wizards |
| `res.device` | Thiết bị người dùng |

### 4.3 Các thành phần khác

- **Security**: Groups, access rules, record rules
- **Report**: Paper formats, report layouts
- **Assets**: Web asset management
- **Wizards**: Module install/update, language import/export, partner merge

---

## 5. Frontend Architecture

### 5.1 OWL Framework

Odoo sử dụng **OWL (Odoo Web Library)** - framework JavaScript tự phát triển, dựa trên reactive components, tương tự React/Vue.

```
addons/web/static/src/
├── core/           # Core utilities & components
├── model/          # Data model layer (RPC)
├── views/          # View types (list, form, kanban, ...)
├── search/         # Search bar, filters, group by
├── webclient/      # Main web client shell
├── libs/           # Third-party libraries
├── scss/           # SCSS styles
├── public/         # Public pages
├── legacy/         # Legacy compatibility
├── polyfills/      # Browser polyfills
├── env.js          # OWL environment setup
├── main.js         # App entry point
├── start.js        # Bootstrap
├── session.js      # Session management
└── module_loader.js # ES module loader
```

### 5.2 Web Client

Odoo Web Client là **Single Page Application (SPA)** với các thành phần:

- **Action Manager**: Điều phối giữa các views/actions
- **View Types**: Form, List, Kanban, Calendar, Pivot, Graph, Map, Activity, Cohort
- **Search Panel**: Filters, Group By, Favorites
- **Navigation**: Menu, breadcrumbs, paging

### 5.3 View System

Odoo sử dụng XML để định nghĩa views, được render thành OWL components:

```xml
<record model="ir.ui.view" id="view_name">
    <field name="name">view.name</field>
    <field name="model">model.name</field>
    <field name="arch" type="xml">
        <form>
            <field name="name"/>
            <field name="value"/>
        </form>
    </field>
</record>
```

### 5.4 Asset Bundle System

Odoo quản lý JS/CSS assets qua bundle system trong `__manifest__.py`:

```python
'assets': {
    'web.assets_backend': ['module/static/src/**/*.js'],
    'web.assets_frontend': ['module/static/src/public/**/*.js'],
}
```

### 5.5 Real-time Communication (`addons/bus/`)

Module **IM Bus** cung cấp giao tiếp real-time:

- **WebSocket** cho kết nối hai chiều
- **Long polling** fallback
- Sử dụng cho: notifications, live chat, collaborative editing, status updates

### 5.6 Website Builder & HTML Editor

- **`html_editor/`**: Rich text editor (WYSIWYG) tích hợp
- **`html_builder/`**: Drag-and-drop website builder
- **`website/`**: Enterprise website builder với SEO, themes, pages

---

## 6. Addon Modules

### 6.1 Thống kê

| Nhóm | Số lượng | Mô tả |
|------|----------|--------|
| **Tổng cộng** | **612** | Tất cả addons |
| `l10n_*` | 212 | Localization (kế toán theo quốc gia) |
| `website_*` | 54 | Website features |
| `pos_*` | 38 | Point of Sale extensions |
| `hr_*` | 27 | Human Resources extensions |
| `test_*` | 17 | Test modules |

### 6.2 Modules nghiệp vụ chính

#### Tài chính & Kế toán

| Module | Tên | Mô tả |
|--------|-----|--------|
| `account` | Invoicing | Quản lý hóa đơn, thanh toán, kế toán phân tích & tài chính |
| `account_payment` | Payment | Đăng ký thanh toán |
| `account_check_printing` | Check Printing | In séc thanh toán |
| `account_edi` | Electronic Invoicing | Hóa đơn điện tử |
| `account_peppol` | PEPPOL | Kết nối mạng PEPPOL |

#### Bán hàng

| Module | Tên | Mô tả |
|--------|-----|--------|
| `sale` | Sales | Quản lý đơn hàng, báo giá |
| `sale_management` | Sales Management | Mẫu báo giá, cổng khách hàng |
| `sale_crm` | Sale CRM | Liên kết Sales - CRM |
| `sale_stock` | Sale Stock | Liên kết Sales - Kho |
| `sale_mrp` | Sale MRP | Liên kết Sales - Sản xuất |

#### Mua hàng

| Module | Tên | Mô tả |
|--------|-----|--------|
| `purchase` | Purchase | Đơn mua hàng, đấu thầu, hợp đồng |
| `purchase_stock` | Purchase Stock | Liên kết Mua hàng - Kho |
| `purchase_requisition` | Purchase Agreements | Hợp đồng mua hàng |

#### Kho & Logistics

| Module | Tên | Mô tả |
|--------|-----|--------|
| `stock` | Inventory | Quản lý kho, logistics, stock moves |
| `stock_account` | Stock Accounting | Kế toán kho |
| `stock_landed_costs` | Landed Costs | Chi phí vận chuyển phân bổ |
| `delivery` | Delivery | Phương thức giao hàng |
| `stock_picking_batch` | Batch Picking | Lấy hàng theo lô |

#### Sản xuất

| Module | Tên | Mô tả |
|--------|-----|--------|
| `mrp` | Manufacturing | Lệnh sản xuất, BOM (Bill of Materials) |
| `mrp_account` | MRP Accounting | Kế toán sản xuất |
| `mrp_subcontracting` | Subcontracting | Gia công ngoài |

#### CRM & Marketing

| Module | Tên | Mô tả |
|--------|-----|--------|
| `crm` | CRM | Theo dõi leads, cơ hội kinh doanh |
| `mass_mailing` | Email Marketing | Chiến dịch email marketing |
| `marketing_card` | Marketing Card | Thẻ marketing |
| `utm` | UTM Trackers | Tracking nguồn marketing |

#### Nhân sự

| Module | Tên | Mô tả |
|--------|-----|--------|
| `hr` | Employees | Quản lý thông tin nhân viên |
| `hr_attendance` | Attendance | Chấm công |
| `hr_holidays` | Time Off | Quản lý nghỉ phép |
| `hr_expense` | Expenses | Chi phí công tác |
| `hr_recruitment` | Recruitment | Tuyển dụng |
| `hr_timesheet` | Timesheet | Chấm công theo dự án |
| `hr_skills` | Skills | Quản lý kỹ năng nhân viên |
| `hr_homeworking` | Homeworking | Làm việc từ xa |

#### Dịch vụ & Dự án

| Module | Tên | Mô tả |
|--------|-----|--------|
| `project` | Project | Quản lý dự án, task, Kanban |
| `project_timesheet` | Project Timesheet | Timesheet theo dự án |

#### Website & eCommerce

| Module | Tên | Mô tả |
|--------|-----|--------|
| `website` | Website | Website builder kéo thả |
| `website_sale` | eCommerce | Cửa hàng trực tuyến |
| `website_blog` | Blog | Hệ thống blog |
| `website_forum` | Forum | Diễn đàn hỏi đáp |
| `website_event` | Events | Sự kiện trực tuyến |
| `website_slides` | eLearning | Nền tảng học trực tuyến |

#### Giao tiếp

| Module | Tên | Mô tả |
|--------|-----|--------|
| `mail` | Discuss | Chat, email gateway, kênh riêng |
| `im_livechat` | Live Chat | Chat trực tiếp với khách hàng |
| `sms` | SMS | Gửi tin nhắn SMS |

#### Point of Sale

| Module | Tên | Mô tả |
|--------|-----|--------|
| `point_of_sale` | POS | Bán hàng tại quầy, thanh toán |
| `pos_restaurant` | POS Restaurant | Mở rộng POS cho nhà hàng |
| `pos_self_order` | Self Order | Tự gọi món qua điện thoại |

#### Thanh toán điện tử

| Module | Tên | Mô tả |
|--------|-----|--------|
| `payment` | Payment | Framework thanh toán |
| `payment_stripe` | Stripe | Tích hợp Stripe |
| `payment_paypal` | PayPal | Tích hợp PayPal |
| `payment_adyen` | Adyen | Tích hợp Adyen |
| ... | ... | +15 nhà cung cấp khác |

#### Khác

| Module | Tên | Mô tả |
|--------|-----|--------|
| `fleet` | Fleet | Quản lý đội xe |
| `event` | Events | Quản lý sự kiện |
| `survey` | Surveys | Khảo sát trực tuyến |
| `lunch` | Lunch | Đặt cơm trưa |
| `maintenance` | Maintenance | Bảo trì thiết bị |
| `loyalty` | Loyalty | Chương trình khách hàng thân thiết |
| `spreadsheet` | Spreadsheet | Bảng tính tích hợp |
| `gamification` | Gamification | Game hóa KPI |

### 6.3 Localization Modules (`l10n_*`)

212 module bản địa hóa cho hệ thống kế toán theo từng quốc gia, bao gồm:
- Chart of Accounts (hệ thống tài khoản)
- Tax configuration (cấu hình thuế)
- Electronic invoicing (hóa đơn điện tử)
- Country-specific reports (báo cáo theo quốc gia)
- Fiscal positions (vị trí tài chính)

---

## 7. Công nghệ & Dependencies

### 7.1 Backend (Python)

| Package | Mục đích |
|---------|----------|
| `Werkzeug` | WSGI HTTP framework |
| `psycopg2` | PostgreSQL adapter |
| `lxml` | XML/HTML processing |
| `Jinja2` | Template engine |
| `Pillow` | Image processing |
| `reportlab` | PDF generation |
| `gevent/greenlet` | Async server (Linux) |
| `passlib` | Password hashing |
| `cryptography/pyopenssl` | TLS/SSL |
| `requests` | HTTP client |
| `Babel` | Internationalization |
| `libsass` | SCSS compilation |
| `xlrd/XlsxWriter/openpyxl` | Excel import/export |
| `PyPDF2/PyPDF` | PDF manipulation |
| `qrcode` | QR code generation |
| `num2words` | Number to words conversion |
| `python-ldap` | LDAP authentication |
| `zeep` | SOAP client |
| `vobject` | vCard/iCalendar |
| `python-stdnum` | Number validation (VAT, IBAN, ...) |
| `psutil` | System monitoring |
| `geoip2` | IP geolocation |

### 7.2 Frontend

| Technology | Mục đích |
|------------|----------|
| **OWL** | Reactive component framework (tự phát triển) |
| **QWeb** | Template engine (XML-based) |
| **SCSS** | CSS preprocessor |
| **ES Modules** | JavaScript module system |

### 7.3 Cơ sở dữ liệu

- **PostgreSQL 13+**
- Multi-database architecture (mỗi database = 1 instance độc lập)
- Connection pooling
- Read replica support

---

## 8. Security Architecture

### 8.1 Authentication

| Phương thức | Module |
|-------------|--------|
| Password (PBKDF2) | `base` |
| OAuth 2.0 | `auth_oauth` |
| LDAP | `auth_ldap` |
| TOTP (2FA) | `auth_totp` |
| Passkey (WebAuthn) | `auth_passkey` |
| API Keys | `base` (res.users.apikeys) |

### 8.2 Authorization

- **Groups**: Phân nhóm quyền (`res.groups`)
- **Access Control Lists**: Quyền trên model (CRUD)  - `ir.model.access`
- **Record Rules**: Quyền trên record level - `ir.rule` (domain-based)
- **Field-level access**: Groups trên từng field
- **Multi-company**: Isolate dữ liệu giữa các công ty

### 8.3 Bảo mật khác

- **CSRF Protection**: Token-based
- **Password Policy**: `auth_password_policy`
- **Session Timeout**: `auth_timeout`
- **reCAPTCHA**: `google_recaptcha`
- **Cloudflare Turnstile**: `website_cf_turnstile`

---

## 9. Deployment & Configuration

### 9.1 Cấu hình chính

Cấu hình qua file `odoo.conf` hoặc command-line arguments:

| Tham số | Mô tả |
|---------|--------|
| `db_host`, `db_port`, `db_user`, `db_password` | Kết nối PostgreSQL |
| `db_name` | Database name(s) |
| `db_replica_host`, `db_replica_port` | Read replica |
| `addons_path` | Đường dẫn tìm modules |
| `http_port` | HTTP port (mặc định 8069) |
| `workers` | Số worker processes (0 = threaded) |
| `proxy_mode` | Chạy sau reverse proxy |
| `dev_mode` | Chế độ development (reload, assets, ...) |
| `pidfile` | PID file path |
| `config` | Đường dẫn config file |

### 9.2 Chế độ chạy

```
# Development (threaded)
./odoo-bin --dev=all -d mydb

# Production (prefork)
./odoo-bin --workers=4 --proxy-mode -d mydb

# Gevent (long polling / websocket)
./odoo-bin --workers=4 --gevent-port=8072
```

### 9.3 Module Lifecycle

```
Uninstalled → Installing → Installed → Upgrading → Installed
                                     → Uninstalling → Uninstalled
```

---

## 10. Tính năng kỹ thuật nổi bật

### 10.1 Multi-company

- Hỗ trợ nhiều công ty trong 1 database
- Record rules tự động filter theo công ty
- Company-dependent fields

### 10.2 Multi-language (i18n)

- Hỗ trợ đa ngôn ngữ hoàn toàn
- Lazy translation với `_()` function
- Export/import PO files

### 10.3 Reporting

- **QWeb Reports**: PDF reports từ HTML templates
- **Spreadsheet**: Bảng tính tích hợp với pivot, charts
- **Dashboard**: Dashboard builder

### 10.4 Automated Actions

- `ir.cron`: Scheduled jobs
- `base.automation`: Trigger-based automation rules
- Server actions: Python code, email, SMS

### 10.5 Data Import/Export

- CSV import
- Excel import/export
- XML data files
- REST API (JSON-RPC, XML-RPC)

### 10.6 Audit & Logging

- `mail.tracking.value`: Field change tracking
- `ir.logging`: System logs
- `ir.profile`: Performance profiling (speedscope)

---

## 11. API & Integration

### 11.1 RPC Protocols

| Protocol | Endpoint | Mô tả |
|----------|----------|--------|
| JSON-RPC 2.0 | `/jsonrpc` | Primary API protocol |
| XML-RPC | `/xmlrpc/2/` | Legacy protocol |

### 11.2 REST Controllers

Custom HTTP routes qua `@http.route()`:
- `type='json'`: JSON request/response
- `type='http'`: Standard HTTP
- `auth='user'` / `auth='public'` / `auth='none'`

### 11.3 External API

```python
# JSON-RPC example
import jsonrpcclient
result = jsonrpcclient.request(
    "http://localhost:8069/jsonrpc",
    "call",
    service="object",
    method="execute_kw",
    args=[db, uid, password, 'res.partner', 'search_read', [[]], {'fields': ['name']}]
)
```

### 11.4 IAP (In-App Purchase)

Module `iap` cung cấp framework cho dịch vụ trả phí tích hợp (OCR, SMS, email validation, ...).

---

## 12. Testing

### 12.1 Test Framework

- Dựa trên `unittest` của Python
- `TransactionCase`: Mỗi test trong 1 transaction (rollback)
- `SingleTransactionCase`: Nhiều tests chia sẻ transaction
- `HttpCase`: Test HTTP endpoints & web client
- `tagged()`: Gắn tag cho test để chạy selective

### 12.2 Frontend Testing

- **Tour tests**: Automated UI tests qua `web_tour`
- Chạy trên Chrome headless

### 12.3 Chạy tests

```bash
./odoo-bin -d testdb --test-enable --test-tags=/module_name
```

---

*Tài liệu được tạo tự động từ codebase Odoo 19.0*
