# پاپیلیو

[English](README.md) · [وضعیت قابلیت‌ها](TODO.md) · [راهنمای استفاده](docs/user-guide.fa.md)

پنل مستقل با مجوز MIT که با Django و Vue بازسازی می‌شود. هدف مرحله‌ای پروژه،
مدیریت هسته و نود، اشتراک، فروش، پرداخت، بات تلگرام و اتصال برنامهٔ اندروید است.

## وضعیت فعلی

**نسخهٔ 0.1.0-alpha.3 یک انتشار آزمایشی است؛ MVP فروش سرویس هنوز در حال ساخت است.**
[وضعیت انتشار](https://github.com/stupidprogrammer4/papilio-proxy/releases/tag/v0.1.0-alpha.3).

Alpha.3 تفاوت شناسهٔ ایمیج در Docker29 تمیز را اصلاح می‌کند. بستهٔ OCI هر دو
شناسهٔ manifest و config را ثبت می‌کند؛ انتشار به آزمون واقعی هر دو نوع مخزن
classic و containerd روی دو معماری وابسته است. نصب عمومی alpha.3 در حالت
production/HTTP روی Ubuntu24.04 amd64 تمیز، ورود مالک، تغییر زمان‌بندی و اجرای
واقعی worker را گذرانده است. [جزئیات نصب و زمان‌ها](docs/installation-matrix.md).

راه‌اندازی مالک، ورود با نشست و CSRF، عملیات پس‌زمینه، workerهای CPU و ارتباطی،
زمان‌بندی قابل ویرایش، ثبت نود و صدور فایل mTLS، تنظیم بات هر اپراتور و اتصال ادمین،
ویزارد نصب و ایمیج آماده را دارد. بکاپ، بازیابی و ارتقا از alpha.1 با حفظ حساب،
رمز و زمان‌بندی تغییرکرده آزموده شده‌اند.

نصب خودکار هسته، ساخت سرویس از Django، اشتراک، محصول، کیف پول، تأیید پرداخت،
خرید و تحویل با بات و تطبیق پرداخت اندروید هنوز تکمیل نشده‌اند. وجود صفحه‌های
فرانت به معنی اتصال بک‌اند آن‌ها نیست. [وضعیت عامل](node/agent/README.fa.md) و
[فهرست قابلیت‌ها](TODO.md) مرز فعلی را مشخص می‌کنند. آزمون بات در مرورگر و worker
از سرویس آزمایشی تلگرام استفاده می‌کند؛ بررسی هویت در API واقعی، خرید واقعی نیست.

در main، API ثبت هسته و inbound موجود، ساخت پایدار سرویس با worker ارتباطی
و اشتراک امضاشدهٔ VLESS اضافه شده است. [راهنمای API توسعه](docs/user-guide.fa.md)
حد نمونهٔ TCP نامحدود و کارهای باقی‌ماندهٔ چرخهٔ سرویس، پنل و فروش را مشخص می‌کند.
این بخش جدا از فایل‌های منتشرشدهٔ alpha.3 است.

## نصب

روی سرور تمیز Ubuntu/Debian از ماتریس اولیه:

```sh
sudo bash -c 'set -euo pipefail; if ! command -v curl >/dev/null || [ ! -s /etc/ssl/certs/ca-certificates.crt ]; then apt-get update; DEBIAN_FRONTEND=noninteractive apt-get install -y curl ca-certificates; fi; curl -fsSL https://raw.githubusercontent.com/stupidprogrammer4/papilio-proxy/main/install.sh | bash -s --'
```

اسکریپت راه‌انداز از main دریافت می‌شود و فعلاً بسته‌های ثابت alpha.3 را نصب می‌کند.
پیش‌نیازهای موجود دوباره نصب نمی‌شوند؛ فهرست مخزن Docker جدا دریافت می‌شود و
فهرست کامل سیستم فقط در صورت کمبود وابستگی لازم است.

ویزارد، محیط، دامنه/IP و HTTP یا HTTPS را می‌گیرد. F3 تنظیمات شناسه، پورت، نشانی
شنود و روش ایمیج‌ها را باز می‌کند؛ F2 مرور تنظیمات، Tab و کلیدهای جهت برای حرکت و
Esc برای لغو هستند. مقادیر نصب قبلی حفظ می‌شوند و ترمینال ساده فرم متنی دارد.
وابستگی اضافه‌ای برای UI نصب نمی‌شود. محیط اولیهٔ bootstrap برابر production است.

نصب بدون تعامل با HTTP روی یک سرور:

```sh
sudo bash -c 'set -euo pipefail; if ! command -v curl >/dev/null || [ ! -s /etc/ssl/certs/ca-certificates.crt ]; then apt-get update; DEBIAN_FRONTEND=noninteractive apt-get install -y curl ca-certificates; fi; curl -fsSL https://raw.githubusercontent.com/stupidprogrammer4/papilio-proxy/main/install.sh | bash -s -- --non-interactive --environment production --host panel.example.com --scheme http'
```

HTTP با دامنه یا IPv4 کار می‌کند و فقط پورت HTTP انتخابی باز می‌شود. HTTPS اختیاری
است؛ برای آن `--scheme https`، DNS درست و دسترسی لازم برای صدور گواهی را فراهم
کنید. در صورت حذف گزینه، پیش‌فرض production برابر HTTPS و بقیه HTTP است.
`--interactive` با ورودی pipe هم فرم را باز می‌کند.

نصاب عمومی، ایمیج تأییدشدهٔ بک‌اند، فرانت، PostgreSQL، Redis و RabbitMQ را بدون
build برنامه روی سرور یا ورود به رجیستری بارگذاری می‌کند. با
`--image-mode auto|prebuilt|build` در فرم پیشرفته یا خط فرمان روش را انتخاب کنید.
فایل خراب یا ناموجود، نصب را متوقف می‌کند؛ برای ساخت از سورس `build` را صریح
انتخاب کنید. این انتخاب با restart و update حفظ می‌شود. سورس بدون manifest در
حالت auto روی سرور build می‌شود:

```sh
sudo bash ./install.sh --source "$PWD"
```

نصاب آدرس راه‌اندازی، توکن یک‌بارمصرف پنج‌دقیقه‌ای و فرمان `papilio` را فراهم
می‌کند. محیط‌های `dev`، `test`، `sandbox` و `production` داده، کلید، شبکه، صف و کش
جدا دارند. sandbox پیش‌فرض روی localhost است؛ برای دسترسی از راه دور از
`ssh -L 8080:127.0.0.1:8080 user@server` استفاده کنید. نصب اضافه با `--instance`
و پورت‌های مجزای `--port` و `--https-port` ساخته می‌شود. اگر `papilio` متعلق به
نصب دیگری باشد، فرمان `papilio-INSTANCE-ENVIRONMENT` ساخته می‌شود؛ فرمان نامرتبط
یا تغییریافتهٔ کاربر بازنویسی نمی‌شود. [ماتریس آزمون](docs/installation-matrix.md)
دامنهٔ پشتیبانی واقعی را مشخص می‌کند.

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
فرمان alpha.2 از نصاب خود نسخهٔ مقصد استفاده می‌کند. bootstrap فعلی هم با
`--update` بدون ورود دوبارهٔ دامنه، نصب موجود را ارتقا می‌دهد. ارتقای واقعی alpha.1 به alpha.2 و بازیابی بکاپ روی نصب تازهٔ alpha.1 در sandbox
آزموده شده‌اند؛ این به معنی پشتیبانی از downgrade درجا یا مهاجرت از پیاده‌سازی
حذف‌شده نیست. [راهنمای ارتقا](docs/user-guide.fa.md) را ببینید.

## مسیر توسعه

در شاخهٔ توسعهٔ `main`، صفحهٔ سرویس به ساخت واقعی Xray و اشتراک وصل شده و
کنترل مشتری/کیف پول ریالی، دفتر دقیق موجودی و ویرایش سقف اعتبار نیز وجود دارد.
این تغییرات در بستهٔ منتشرشدهٔ alpha.3 نیستند؛ [راهنمای فارسی](docs/user-guide.fa.md)
رفتار و محدودیت‌های فعلی را توضیح می‌دهد.

پایهٔ انتشار ← Xray و خرید واقعی با بات ← تکمیل پاسارگارد ← فروش و بات کامل ←
هسته‌ها و شبکه ← اندروید و پرداخت خودکار ← تبلیغات و تکمیل نسخهٔ ۱.

کد خود پروژه MIT است؛ وابستگی‌ها و هسته‌های خارجی با مجوز اصلی خود باقی می‌مانند.
ویژگی‌ها مستقل پیاده‌سازی می‌شوند. وضعیت و معیار پذیرش هر بخش در
[فهرست عمومی قابلیت‌ها](docs/feature-catalog.json) و [TODO](TODO.md) ثبت است.
