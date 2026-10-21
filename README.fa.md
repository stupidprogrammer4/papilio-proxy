# پاپیلیو

[English](README.md) · [وضعیت قابلیت‌ها](TODO.md) · [راهنمای استفاده](docs/user-guide.fa.md)

پنل مستقل با مجوز MIT که با Django و Vue بازسازی می‌شود. هدف مرحله‌ای پروژه،
مدیریت هسته و نود، اشتراک، فروش، پرداخت، بات تلگرام و اتصال برنامهٔ اندروید است.

## وضعیت فعلی

**نسخهٔ 0.1.0-alpha.1 پایهٔ آزمایشی است؛ هنوز MVP فروش سرویس نیست.**
[دریافت نسخه](https://github.com/stupidprogrammer4/papilio-proxy/releases/tag/v0.1.0-alpha.1).
راه‌اندازی مالک، ورود با نشست و CSRF، صفحهٔ وضعیت، عملیات پایدار پس‌زمینه، workerهای
جدا برای ارتباطات و CPU، زمان‌بندی قابل ویرایش در دیتابیس و CLI نصب و بکاپ را دارد.
ساخت واقعی سرویس Xray، اشتراک، فروش، بات متصل و تطبیق پرداخت اندروید در تحویل‌های
بعدی هستند. وجود سورس نگه‌داشته‌شدهٔ فرانت و اندروید به معنی اتصال قابلیت‌هایشان
به بک‌اند تازه نیست.

در شاخهٔ main، عامل اجرایی Go با mTLS روی Xray و کلاینت واقعی آزموده شده است؛
صدور گواهی نود در worker پردازشی و ثبت و بررسی اتصال عامل موجود از صفحهٔ نودها
اضافه شده است. نصب خودکار، مدیریت فرایند هسته و فروش هنوز در حال ساخت‌اند. این کد در
بستهٔ پایهٔ بالا وجود ندارد. [وضعیت عامل نود](node/agent/README.fa.md) مرز فعلی را
مشخص می‌کند.

## نصب

روی یک Ubuntu/Debian تمیز از ماتریس اولیه:

```sh
sudo bash -c 'set -euo pipefail; apt-get update; apt-get install -y curl ca-certificates; curl -fsSL https://raw.githubusercontent.com/stupidprogrammer4/papilio-proxy/v0.1.0-alpha.1/install.sh | bash -s -- --environment sandbox'
```

نصاب وابستگی‌ها و سرویس‌ها را آماده می‌کند و آدرس راه‌اندازی و توکن یک‌بارمصرف با
اعتبار پنج دقیقه را نمایش می‌دهد. حالت sandbox پیش‌فرض فقط روی localhost است؛
برای دسترسی از کامپیوتر خودتان تونل بزنید:

```sh
ssh -L 8080:127.0.0.1:8080 user@server
```

برای حالت production، دامنه را به سرور متصل و پورت‌های صدور گواهی را در دسترس کنید:

```sh
sudo bash -c 'set -euo pipefail; apt-get update; apt-get install -y curl ca-certificates; curl -fsSL https://raw.githubusercontent.com/stupidprogrammer4/papilio-proxy/v0.1.0-alpha.1/install.sh | bash -s -- --environment production --host panel.example.com'
```

محیط‌های `dev`، `test`، `sandbox` و `production` داده، کلید، شبکهٔ Docker، صف و کش
جدا دارند. نصب‌های اضافه با `--instance NAME` و پورت مجزا از `--port PORT` ساخته
می‌شوند. production گزینهٔ `--https-port PORT` هم دارد.
[ماتریس آزمون نصب](docs/installation-matrix.md) مشخص می‌کند کدام ترکیب واقعاً اجرا
شده؛ همهٔ نسخه‌ها، معماری‌ها و سیستم‌عامل‌ها هنوز تأیید نشده‌اند.
اگر فرمان `papilio` متعلق به نصب دیگری باشد، نصاب فرمان مستقل
`papilio-INSTANCE-ENVIRONMENT` می‌سازد و نام آن را نمایش می‌دهد. فایل فرمان نامرتبط
یا تغییریافتهٔ کاربر بازنویسی نمی‌شود.

## فرمان‌های معمول

```sh
sudo papilio status
sudo papilio doctor
sudo papilio logs --tail 100
sudo papilio stop
sudo papilio start
sudo papilio restart
sudo papilio backup
sudo papilio restore /private/path/backup.tar.gz
sudo papilio update
```

توقف، داده‌ها را نگه می‌دارد. بازیابی ابتدا فایل را بررسی و از وضعیت فعلی بکاپ
می‌گیرد؛ نسخهٔ برنامه، محیط و شناسهٔ نصب باید سازگار باشند. برای انتخاب نسخهٔ
به‌روزرسانی از `update --version VERSION` یا `update --source DIR` استفاده کنید.
این اولین انتشار Django است و ادعای آزمون ارتقا از یک نسخهٔ قبلیِ پشتیبانی‌شده ندارد.

## مسیر توسعه

پایهٔ انتشار ← Xray و خرید واقعی با بات ← تکمیل پاسارگارد ← فروش و بات کامل ←
هسته‌ها و شبکه ← اندروید و پرداخت خودکار ← تبلیغات و تکمیل نسخهٔ ۱.

کد خود پروژه MIT است؛ وابستگی‌ها و هسته‌های خارجی با مجوز اصلی خود باقی می‌مانند.
ویژگی‌ها مستقل پیاده‌سازی می‌شوند. وضعیت و معیار پذیرش هر بخش در
[فهرست عمومی قابلیت‌ها](docs/feature-catalog.json) و [TODO](TODO.md) ثبت است.
