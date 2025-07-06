Assalomu alaykum.

Loyihaning "yuragi" bo'lgan `core` modulining to'liq tahlilini boshlaymiz. Siz taqdim etgan fayllar asosida, men ushbu modulning har bir komponenti bo'yicha batafsil dokumentatsiya va professional hisobot tayyorladim.

`core` moduli — bu sizning userbotingizning butun ishlash mantig'i, poydevori va "dvigateli"dir. Uning arxitekturasi juda puxta o'ylangan va zamonaviy dasturlash amaliyotlariga asoslangan.

-

#`core` Moduli Bo'yicha To'liq Hisobot (1-qism)

#1. `config.py` — Sozlamalar Tuzilmasi

* Maqsadi: Dasturning barcha sozlamalari uchun aniq va qat'iy tuzilmani (sxemani) belgilash. Bu fayl "qanday sozlamalar bo'lishi kerak va ular qanday formatda bo'lishi lozim" degan savolga javob beradi.
* Asosiy Komponentlar va Imkoniyatlar:
    * `StaticSettings` (klass): `Pydantic` kutubxonasiga asoslangan bu klass `.env` faylidagi barcha o'zgaruvchilarni (masalan, `OWNER_ID`, `DB_PATH`, `API_KEY`lar) o'qiydi, ularni tekshiradi (validatsiya qiladi) va kerakli tiplarga (masalan, `int`, `str`, `Path`) o'giradi.
    * Validatsiya: Sozlamalarning to'g'riligini avtomatik tekshiradi. Masalan, `OWNER_ID` ko'rsatilmagan bo'lsa yoki `LOG_LEVEL` noto'g'ri qiymatga ega bo'lsa, dastur ishga tushishidan oldin xatolik beradi.
* Tizimdagi O'rni: Bu modul — sozlamalar uchun "qolip" vazifasini bajaradi. `ConfigManager` bu qolipdan foydalanib, sozlamalarni o'qiydi va boshqaradi.

-

#2. `config_manager.py` — Sozlamalar Menejeri

* Maqsadi: Statik (`.env` faylidan) va dinamik (ma'lumotlar bazasidan) sozlamalarni yagona nuqtadan boshqarish.
* Asosiy Komponentlar va Imkoniyatlar:
    * `ConfigManager` (klass): Bu sinf `config.py`'dagi `StaticSettings`'ni va ma'lumotlar bazasini o'zida birlashtiradi.
    * `.get()` va `.set()` metodlari: Dasturning istalgan qismidan biror sozlamani olish yoki o'rnatish uchun yagona va qulay interfeysni taqdim etadi. Agar sozlama dinamik bo'lsa, u bazadan o'qiydi yoki bazaga yozadi.
* Tizimdagi O'rni: Dasturning barcha qismlari sozlamalarni bevosita fayllardan yoki bazadan emas, balki shu menejer orqali oladi. Bu kodni tartibli va markazlashgan qiladi.

-

#3. `database.py` — Ma'lumotlar Bazasi Boshqaruvchisi

* Maqsadi: SQLite ma'lumotlar bazasi bilan asinxron va xavfsiz ishlash uchun to'liq qatlam (abstraction layer) yaratish.
* Asosiy Komponentlar va Imkoniyatlar:
    * `AsyncDatabase` (klass): Bazaga ulanish, so'rovlarni bajarish (`fetchall`, `fetchone`, `execute`), tranzaksiyalarni boshqarish va zaxira nusxalarini olish kabi barcha amallarni o'z ichiga oladi.
    * Migratsiya Tizimi: Dastur ishga tushganda `yoyo-migrations` yordamida `data/migrations` papkasidagi o'zgarishlarni avtomatik ravishda bazaga tatbiq etadi. Bu baza sxemasini versiyalash va yangilab borish imkonini beradi.
    * Xatoliklarni Boshqarish: `retry_on_lock` dekoratori yordamida baza "band" bo'lib qolganida so'rovni bir necha marta qayta urinib ko'radi, bu esa barqarorlikni oshiradi.
* Tizimdagi O'rni: Ma'lumotlarni saqlash va o'qish uchun mas'ul bo'lgan markaziy komponent.

-

#4. `db_utils.py` va `db_whitelists.py` — Baza Yordamchilari va Xavfsizlik

* Maqsadi: `database.py` ishlatadigan quyi darajadagi yordamchi funksiyalarni va xavfsizlik qoidalarini o'zida saqlash.
* Asosiy Komponentlar va Imkoniyatlar:
    * `_run_migrations_util`, `_create_backup_util`: Migratsiya va zaxira nusxalash kabi murakkab amallarning logikasini saqlaydi.
    * `_validate_table_name_util`: `db query` kabi buyruqlar orqali yuborilgan SQL so'rovlarida faqat ruxsat etilgan jadvallar ishlatilayotganini tekshiradi.
    * `DB_TABLE_WHITELIST`, `DB_COLUMN_WHITELIST`: `.db query` buyrug'i orqali qaysi jadval va ustunlarga murojaat qilish mumkinligini belgilovchi "oq ro'yxat". Bu SQL in'yeksiya hujumlaridan va ma'lumotlar sizib chiqishidan himoyalanish uchun juda muhim xavfsizlik chorasi.
* Tizimdagi O'rni: Ma'lumotlar bazasi bilan ishlashda xavfsizlik va tartibni ta'minlaydi.

-

#5. `cache.py` — Kesh Menejeri

* Maqsadi: Tez-tez so'raladigan, lekin kam o'zgaradigan ma'lumotlarni vaqtinchalik xotirada saqlab, dastur tezligini va unumdorligini oshirish.
* Asosiy Komponentlar va Imkoniyatlar:
    * `CacheManager` (klass): Nomlar makoni (`namespace`) bo'yicha keshlashni qo'llab-quvvatlaydi. Masalan, "auth" va "entity" keshlarini bir-biridan alohida saqlaydi.
    * TTL va LRU Siyosatlari: Har bir kesh yozuvi uchun "yashash vaqti" (TTL) belgilash va kam ishlatiladigan eski ma'lumotlarni avtomatik o'chirish (LRU) imkoniyati mavjud.
    * Diskka Saqlash: Dastur to'xtatilganda keshni faylga saqlab qo'yadi va qayta ishga tushganda tiklaydi.
* Tizimdagi O'rni: Ma'lumotlar bazasiga va tashqi API'larga qilinadigan murojaatlar sonini kamaytirib, botning javob berish tezligini oshiradi.

-

#6. `state.py` — Dastur Holati Menejeri

* Maqsadi: Dasturning ishlash jarayonidagi "jonli" ma'lumotlarni saqlash (masalan, `.sudo` rejimi yoqilganmi, qaysi plaginlarda xatolik bor, kim qachon `afk` bo'ldi).
* Asosiy Komponentlar va Imkoniyatlar:
    * `AppState` (klass): Holatlarni saqlash va ularga obuna bo'lish (`subscribe`) imkonini beradi. Biror holat o'zgarganda, unga obuna bo'lgan funksiyalar avtomatik ishga tushadi. Bu reaktiv dasturlashning ajoyib namunasi.
* Tizimdagi O'rni: Dasturning turli qismlari o'rtasida real vaqtda ma'lumot almashish uchun markaziy "e'lonlar taxtasi" vazifasini bajaradi.

-

#7. `client_manager.py` — Klientlar Menejeri

* Maqsadi: Bir yoki bir nechta userbot akkauntlarini (Telethon klientlarini) boshqarish, ularni ishga tushirish, to'xtatish va sessiyalarini nazorat qilish.
* Asosiy Komponentlar va Imkoniyatlar:
    * `ClientManager` (klass): Barcha `TelegramClient` obyektlarini boshqaradi.
    * Interaktiv Kirish: Yangi akkaunt qo'shishda terminal orqali telefon raqami, kod va parolni so'raydi.
    * Bir Nechta Akkaunt: Bir vaqtning o'zida bir nechta userbot akkauntini ishga tushira oladi va ular orasida boshqaruvni ta'minlaydi.
* Tizimdagi O'rni: Telegram bilan aloqaning eng quyi darajasini boshqaradi va plaginlarni ishchi `client` obyektlari bilan ta'minlaydi.

-

#8. `ai_service.py` — Sun'iy Intellekt Xizmati

* Maqsadi: Har xil sun'iy intellekt (Gemini, OpenAI va hk.) provayderlari bilan ishlash uchun yagona, standart interfeys yaratish.
* Asosiy Komponentlar va Imkoniyatlar:
    * Provider Arxitekturasi: `BaseProvider` abstrakt klassi va uning `GeminiProvider` kabi implementatsiyalari yangi AI modellarini qo'shishni osonlashtiradi.
    * Funksionallik: Matn generatsiyasi, suhbatlashish, rasmni tushunish va audioni matnga o'girish kabi vazifalarni o'z ichiga oladi.
    * RAG (Retrieval-Augmented Generation): Google qidiruvi orqali olingan ma'lumotlar bilan AI'ning bilimini kengaytirib, yanada aniqroq javoblar berish imkoniyati mavjud.
* Tizimdagi O'rni: Loyihaga kuchli sun'iy intellekt imkoniyatlarini qo'shadi va barcha AI bilan bog'liq amallarni bir joyga jamlaydi.

-

#9. `app_context.py` — Dastur Konteksti

* Maqsadi: Loyihaning eng markaziy fayli. U yuqorida sanab o'tilgan barcha menejerlarni (`db`, `config`, `cache`, `state`, `client_manager` va hk.) bitta `AppContext` nomli obyektga jamlaydi.
* Asosiy Komponentlar va Imkoniyatlar:
    * `AppContext` (dataclass): Bu obyekt o'zgarmas (`frozen=True`) qilib yaratilgan. Bu — dasturning turli qismlari tasodifan umumiy sozlamalarni o'zgartirib yuborishining oldini oladi va barqarorlikni ta'minlaydi.
* Tizimdagi O'rni: Bu — "yagona haqiqat manbai" (Single Source of Truth). Dasturning istalgan qismi (masalan, plaginlar) shu yagona `context` obyektini qabul qilib, barcha kerakli resurslarga kira oladi. Bu "Dependency Injection" dizayn naqshining a'lo darajadagi qo'llanilishidir.

-

#10. `app_core.py` — Dastur Yadrosi

* Maqsadi: Butun dasturning hayot siklini — ishga tushishidan to to'xtaguncha bo'lgan jarayonni boshqarish.
* Asosiy Komponentlar va Imkoniyatlar:
    * `Application` (klass): Dasturning asosiy "orkestratori".
    * `run()` metodi: Dasturni ishga tushiradi va quyidagi amallarni ketma-ket bajaradi:
        1.  Loglashni sozlaydi.
        2.  Konfiguratsiyani yuklaydi.
        3.  Ma'lumotlar bazasiga ulanadi va migratsiyalarni bajaradi.
        4.  Barcha menejerlarni (`cache`, `state`, `tasks` va hk.) ishga tushiradi.
        5.  Ularning barchasini `AppContext`'ga joylaydi.
        6.  Plaginlarni yuklaydi (`PluginManager` orqali).
        7.  Telethon klient(lar)ini ishga tushiradi.
        8.  Dastur to'xtatilganda (`CTRL+C` bosilganda) barcha resurslarni to'g'ri va xavfsiz yopadi.
* Tizimdagi O'rni: Bu — loyihaning "bosh fayli" (`main.py`) chaqiradigan asosiy yadro. U barcha qismlarni bir-biriga bog'lab, yagona tizim sifatida ishlashini ta'minlaydi.


Assalomu alaykum.

Biz loyihaning markaziy `core` moduli tahlilini yakunlaymiz. Quyida qolgan 4 ta muhim modul va butun dasturni ishga tushiruvchi `main.py` fayli bo‘yicha to‘liq dokumentatsiya va professional hisobotni taqdim etaman.

-

#`core` Moduli Bo'yicha To'liq Hisobot (2-qism)

#11. `exceptions.py` — Maxsus Istisnolar (Xatoliklar) Moduli

* Maqsadi: Butun dastur uchun maxsus, tushunarli xatolik turlarini (`exceptions`) yaratish. Bu standart `ValueError` yoki `TypeError` o‘rniga, muammoning aniq sababini ko‘rsatuvchi xatoliklardan foydalanish imkonini beradi.
* Asosiy Komponentlar va Imkoniyatlar:
    * `UserbotException` (klass): Loyihadagi barcha maxsus xatoliklar uchun umumiy "ota" klass.
    * `ConfigError`, `DatabaseError`, `PluginError` va boshqalar: Har bir modul uchun alohida xatolik klasslari. Masalan, ma’lumotlar bazasida muammo yuzaga kelsa, dastur `DatabaseError`'ni qaytaradi.
* Tizimdagi O'rni: Bu modul kodni "debug" qilishni (tuzatishni) juda osonlashtiradi. Xatolik jurnalini (`log`) o‘qiganda, muammo aynan qaysi komponentda (konfiguratsiyadami, bazadami yoki plagindami) yuz berganini darhol tushunish mumkin bo‘ladi. Bu — barqaror tizim qurishdagi muhim qadam.

-

#12. `scheduler.py` — Rejalashtiruvchi Menejeri

* Maqsadi: Vazifalarni ma'lum bir vaqtda (masalan, "har kuni soat 9:00 da") yoki ma'lum bir interval bilan (masalan, "har 30 daqiqada") avtomatik ishga tushirishni ta'minlash.
* Asosiy Komponentlar va Imkoniyatlar:
    * `SchedulerManager` (klass): `apscheduler` kutubxonasini o‘zida o‘rab turuvchi (wrapper) asosiy sinf.
    * `.add_job()`, `.remove_job()`: Yangi rejalashtirilgan vazifa qo‘shish yoki mavjudini bekor qilish uchun qulay metodlar.
    * `.get_task_runner()`: `TaskRegistry` bilan integratsiya qilingan holda, rejalashtiruvchi ishga tushirishi kerak bo‘lgan vazifani topib, uni xavfsiz ishga tushirish uchun maxsus "runner" funksiya yaratadi.
* Tizimdagi O'rni: Bu modul `.digest` kabi plaginlarning ishlashi uchun asos bo‘lib xizmat qiladi va userbotga avtomatizatsiya imkoniyatlarini beradi. U "biror narsani keyinroq yoki muntazam bajar" degan buyruqlarni amalga oshiradi.

-

#13. `tasks.py` — Fon Vazifalari Menejeri

* Maqsadi: Uzoq davom etadigan amallarni (masalan, katta faylni yuklash, barcha chatlarni skaner qilish) asosiy oqimni bloklamasdan, orqa fonda (`background`) bajarish.
* Asosiy Komponentlar va Imkoniyatlar:
    * `TaskRegistry` (klass): Barcha fon vazifalarini ro‘yxatdan o‘tkazadi va ularning holatini (ishlayapti, yakunlandi, xatolik berdi) kuzatib boradi.
    * `.register()` (dekorator): Oddiy asinxron funksiyani ro‘yxatdan o‘tgan, boshqariladigan "vazifa"ga aylantiradi.
    * `.run_task_manually()`: Istalgan vazifani qo‘lda ishga tushirish imkonini beradi.
    * Qayta Urinish (Retries): Vazifa xatolik bilan yakunlansa, uni belgilangan son marta avtomatik qayta urinib ko‘rish imkoniyati mavjud.
    * Timeout: Agar vazifa belgilangan vaqtdan uzoqroq ishlab ketsa, uni avtomatik to‘xtatadi.
    * Bog'liqliklarni Uzatish (Dependency Injection): Vazifa ishga tushganda, unga kerakli resurslarni (`client`, `db`, `config`) avtomatik ravishda `AppContext`'dan olib uzatadi.
* Tizimdagi O'rni: Bu modul userbotning bir vaqtning o‘zida bir nechta ishni bajarishini va foydalanuvchi buyruqlariga doimo tez javob berishini ta'minlaydi. Uzoq amallar botni "qotirib qo‘yishining" oldini oladi.

-

#14. `main.py` — Dasturning Kirish Nuqtasi

* Maqsadi: Butun userbot dasturini ishga tushiruvchi yagona va eng asosiy fayl.
* Asosiy Komponentlar va Imkoniyatlar:
    * Bu faylning ichi odatda juda sodda va qisqa bo‘ladi. Uning yagona vazifasi — `core/app_core.py` faylidan `Application` sinfini import qilib, uning `run()` metodini chaqirishdir.
    * Barcha murakkab amallar va sozlamalar `app_core.py` ichida yashiringan bo‘ladi.
* Tizimdagi O'rni: Bu — loyihaning "kaliti". Foydalanuvchi terminalda `python main.py` buyrug‘ini terganida, aynan shu fayl butun mexanizmni harakatga keltiradi.

#Yakuniy Xulosa: `core` Modulining Mukammalligi

Sizning `core` modulingiz — bu zamonaviy, barqaror va kengaytirilishi oson bo‘lgan dasturiy ta'minotning ajoyib namunasidir. Unda qo‘llanilgan yondashuvlar (Dependency Injection, Abstraction Layers, Asynchronous programming, Centralized Management) loyihaning sifatini va ishonchliligini juda yuqori darajaga olib chiqadi. Bu mustahkam poydevor ustiga endi bemalol istalgancha plagin qurish mumkin.

















-------ADMIN----------

Assalomu alaykum.

Siz taqdim etgan `admin` plaginlari to'plamini tahlil qilib chiqdim. Bu shunchaki buyruqlar to'plami emas, bu — to'laqonli, ko'p qirrali va yuqori darajada professional tarzda ishlab chiqilgan boshqaruv paneli.

Har bir plagin o'z vazifasini aniq bajaradi va ular biz avval yaratgan `bot/lib/` kutubxonasining kuchli imkoniyatlaridan unumli foydalanadi. Quyida har bir plagin fayli bo'yicha to'liq dokumentatsiya va tahliliy hisobotni taqdim etaman.

-

#`bot/plugins/admin/` Plaginlari Bo'yicha To'liq Hisobot

#1. `base.py` (ehtimol `base_cmds.py`) — Asosiy Boshqaruv Plagini

* Maqsadi: Userbotning eng asosiy va hayotiy funksiyalarini boshqarish: holatini tekshirish, qayta ishga tushirish va sahifalash (paginatsiya) bilan ishlash.
* Asosiy Buyruqlar:
    * `.ping`: Botning ishlash tezligini tekshiradi.
    * `.status`: Bot, tizim va Telethon versiyalari haqida to'liq hisobot beradi.
    * `.restart` / `.shutdown`: Botni xavfsiz qayta ishga tushiradi yoki o'chiradi (faqat bot egasi uchun).
    * `.sudo`: Xavfli buyruqlar uchun 5 daqiqaga "super foydalanuvchi" rejimini yoqadi.
    * `.next` / `.prev` / `.endp`: `PaginationHelper` orqali yaratilgan sahifalarni boshqarish uchun ishlatiladi.
* Umumiy Tahlil va Yaxshi Tomonlari:
    * Ushbu plagin botning "salomatligi" va asosiy boshqaruvini ta'minlaydi.
    * Huquqlarni tekshirish uchun `@owner_only` kabi dekoratorlardan to'g'ri foydalanilgan.
    * Tizim ma'lumotlarini olish uchun `psutil` kabi kutubxonalarni xavfsiz import qilish amaliyoti qo'llanilgan.

-

#2. `database_cmds.py` — Ma'lumotlar Bazasini Boshqarish Plagini

* Maqsadi: Ma'murga userbotning SQLite ma'lumotlar bazasi bilan to'g'ridan-to'g'ri ishlash imkoniyatini berish.
* Asosiy Buyruqlar:
    * `.db query <SQL>`: Faqat o'qish uchun mo'ljallangan (`SELECT`) SQL so'rovlarini xavfsiz bajaradi.
    * `.db exec <SQL>`: Ma'lumotlarni o'zgartiruvchi (`UPDATE`, `DELETE`) SQL so'rovlarini tasdiqlash so'rovi (`request_confirmation`) bilan birga bajaradi.
    * `.db backup`: Ma'lumotlar bazasining zaxira nusxasini yaratib, uni fayl sifatida yuboradi.
    * `.db status`: Migratsiyalarning holatini (qaysilari bajarilgan, qaysilari kutilayotganini) ko'rsatadi.
* Umumiy Tahlil va Yaxshi Tomonlari:
    * Xavfsizlikka juda katta e'tibor berilgan. Xavfli operatsiyalar faqat bot egasiga ruxsat etilgan va qo'shimcha tasdiqlashni talab qiladi.
    * Natijalarni chiroyli ko'rinishda chiqarish uchun `PaginationHelper` va `format_as_table`'dan unumli foydalanilgan. Bu juda kuchli va professional plagin.

-

#3. `digest.py` (ehtimol `digest_cmds.py`) — Kunlik Hisobot (Dayjest) Plagini

* Maqsadi: Belgilangan vaqtda (masalan, har kuni ertalab) akkauntdagi o'zgarishlar (yangi xabarlar, o'chirilgan xabarlar) haqida umumiy hisobotni avtomatik yaratish va yuborish.
* Asosiy Buyruqlar:
    * `.digest on/off`: Kunlik hisobotni yoqadi yoki o'chiradi.
    * `.digest time HH:MM`: Hisobot yuboriladigan vaqtni o'rnatadi.
    * `.digest now`: Hisobotni hozir darhol generatsiya qilib yuboradi.
    * `.digest status`: Joriy sozlamalar va keyingi yuborish vaqtini ko'rsatadi.
* Umumiy Tahlil va Yaxshi Tomonlari:
    * Loyihaning `core` qismidagi `TaskRegistry` va `SchedulerManager` bilan chuqur integratsiya qilingan. Bu fon rejimida ishlaydigan, rejalashtirilgan vazifalarni yaratishning ajoyib namunasi.
    * Bu plagin userbotni oddiy "buyruq-javob" tizimidan aqlli, avtomatlashtirilgan yordamchiga aylantiradi.

-

#4. `files_cmds.py` — Fayl Menedjeri Plagini

* Maqsadi: Bot ishlayotgan serverning fayl tizimini bevosita Telegram orqali boshqarish.
* Asosiy Buyruqlar:
    * `.ls`: Papka ichidagi fayllar ro'yxatini ko'rsatadi.
    * `.cat <fayl>`: Fayl tarkibini o'qiydi va yuboradi.
    * `.upload <fayl>`: Serverdan Telegramga fayl yuklaydi.
    * `.download`: Xabarga javob berib, undagi faylni serverga yuklab oladi.
    * `.rm`: Fayl yoki papkani o'chiradi (tasdiq bilan).
    * `.mv`: Fayl nomini yoki joylashuvini o'zgartiradi.
* Umumiy Tahlil va Yaxshi Tomonlari:
    * Xavfsizlik eng yuqori darajada! Plagin `bot/lib/system.py`'dagi `resolve_secure_path` kabi yordamchilarni ishlatib, foydalanuvchi loyiha papkasidan tashqaridagi fayllarga teginishiga mutlaqo yo'l qo'ymaydi. Bu — juda muhim va professional yondashuv.

-

#5. `manager_cmds.py` — Plaginlarni Boshqarish Plagini

* Maqsadi: Userbotning o'zini-o'zi boshqarishi uchun markaziy panel. Plaginlarni yoqish, o'chirish va sozlash.
* Asosiy Buyruqlar:
    * `.plugins`: Barcha yuklangan va diskdagi plaginlar ro'yxatini ko'rsatadi.
    * `.load <plagin>`: Yangi plaginni yuklaydi.
    * `.unload <plagin>`: Plaginni xotiradan o'chiradi.
    * `.reload <plagin>`: Plagin kodini yangilab, qayta yuklaydi.
    * `.cmd enable/disable <buyruq>`: Muayyan bir buyruqni vaqtinchalik o'chirib qo'yadi yoki yoqadi.
    * `.phealth`: Plaginlarda yuz bergan xatoliklar tarixini ko'rsatadi.
* Umumiy Tahlil va Yaxshi Tomonlari:
    * Bu plagin butun loyihaning modulli arxitekturasini amalda ko'rsatib beradi. U `bot/loader.py`'dagi `PluginManager` bilan bevosita ishlab, botni o'chirmasdan uning funksionalligini o'zgartirish imkonini beradi.
    * `.phealth` buyrug'i muammolarni aniqlash uchun juda foydali vosita.

-

#6. `log_text.py`, `media_logger.py`, `login_code.py` — Kuzatuv va Xavfsizlik Plaginlari

* Maqsadi: Bu uch plagin akkaunt xavfsizligi va faoliyatini kuzatish uchun birgalikda ishlaydi.
* Asosiy Funksiyalar:
    * `log_text.py`: Barcha kiruvchi, chiquvchi, tahrirlangan va o'chirilgan xabarlarni maxsus log kanaliga yuboradi. O'zgarishlarni ko'rsatish uchun `diff-match-patch`dan foydalanishi — juda ilg'or yechim.
    * `media_logger.py`: Belgilangan chatlardan kelgan barcha media fayllarni (rasm, video, hujjat) alohida log kanaliga saqlaydi. Albomlarni to'g'ri qayta ishlash uchun `asyncio`'dan foydalanishi uning professional yozilganidan dalolat.
    * `login_code.py`: Telegramning o'zidan (777000) kelgan kirish kodlarini avtomatik ushlab, "Saqlangan xabarlar"ga va log kanaliga yuboradi. Bu akkauntga kirishni osonlashtiradi va xavfsizlikni oshiradi.
* Umumiy Tahlil va Yaxshi Tomonlari:
    * Bu plaginlar to'plami userbotni shunchaki yordamchidan to'laqonli monitoring va xavfsizlik vositasiga aylantiradi.


Assalomu alaykum. Admin plaginlari to'plamining ikkinchi qismini ham tahlil qildim. Bu plaginlar loyihangizni boshqarish, kuzatish va sozlash uchun juda kuchli va professional vositalar ekan.

Avvalgi hisobotning davomi sifatida, qolgan plaginlar bo'yicha to'liq dokumentatsiya va tahlilni taqdim etaman.

-

#`bot/plugins/admin/` Plaginlari Bo'yicha Hisobot (Davomi)

#7. `settings_cmds.py` — Sozlamalarni Boshqarish Plagini

* Maqsadi: Userbotning sozlamalarini (`.env` fayli va ma'lumotlar bazasidagi dinamik o'zgaruvchilar) bevosita Telegram orqali boshqarish.
* Asosiy Buyruqlar:
    * `.vars`: Barcha mavjud sozlamalar ro'yxatini ko'rsatadi (qidiruv imkoniyati bilan).
    * `.setvar <kalit> <qiymat>`: Mavjud sozlamaning qiymatini o'zgartiradi.
    * `.delvar <kalit>`: Sozlamani o'chiradi (xavfsizlik uchun tasdiq so'raladi).
    * `.addtovar <kalit> <qiymat>`: Qiymati ro'yxat (`list`) bo'lgan sozlamaga yangi element qo'shadi.
    * `.rmfromvar <kalit> <qiymat>`: Ro'yxatdan elementni olib tashlaydi.
* Umumiy Tahlil va Yaxshi Tomonlari:
    * Xavfsizlik: `PROTECTED_KEYS` ro'yxati orqali botning ishlashi uchun muhim bo'lgan sozlamalarni (masalan, `API_ID`, `OWNER_ID`) o'zgartirishdan himoya qilingan. Bu juda to'g'ri yondashuv.
    * Qulaylik: `parse_string_to_value` yordamchi funksiyasi orqali `.setvar` buyrug'i `true`/`false`, raqamlar va matnlarni avtomatik to'g'ri tipga o'giradi.
    * Interaktivlik: Xavfli amallar (`.delvar`) uchun `request_confirmation`'dan foydalanilgani tasodifiy xatoliklarning oldini oladi.

-

#8. `state_cmds.py` — Holatni Boshqarish Plagini

* Maqsadi: Dasturning ishlash jarayonidagi vaqtinchalik ma'lumotlarni (`state` yoki "holat") ko'rish va boshqarish uchun mo'ljallangan kuchli "debug" vositasi.
* Asosiy Buyruqlar:
    * `.state list`: Holatda saqlanayotgan barcha kalit va qiymatlar ro'yxatini ko'rsatadi.
    * `.state get <kalit>`: Muayyan kalit bo'yicha saqlangan qiymatni batafsil ko'rsatadi.
    * `.state set <kalit> <qiymat>`: Holatga yangi qiymat o'rnatadi.
    * `.state del <kalit>`: Holatdan kalitni o'chiradi.
    * `.state clear`: Barcha (himoyalanmagan) ma'lumotlarni holatdan tozalaydi.
    * `.state listeners`: Holatdagi o'zgarishlarni "tinglayotgan" barcha funksiyalar (callbacks) ro'yxatini ko'rsatadi. Bu juda ilg'or diagnostika funksiyasi.
* Umumiy Tahlil va Yaxshi Tomonlari:
    * Bu plagin dasturchi uchun botni qayta ishga tushirmasdan uning ichki holatini tekshirish va tuzatish uchun beqiyos imkoniyat beradi.
    * `PROTECTED_KEYS` orqali tizimning muhim o'zgaruvchilari himoyalangan.
    * Natijalarni ko'rsatishda `PaginationHelper` va `send_as_file_if_long`'dan foydalanilgani katta hajmdagi ma'lumotlar bilan ishlashni osonlashtiradi.

-

#9. `system.py` (ehtimol `system_cmds.py`) — Tizim Boshqaruvi Plagini

* Maqsadi: Userbot ishlayotgan serverning operatsion tizimi bilan bevosita ishlash, tizim holatini kuzatish va buyruqlar yuborish.
* Asosiy Buyruqlar:
    * `.sh <buyruq>`: Serverda terminal buyrug'ini ishga tushiradi va natijasini oqim (`streaming`) rejimida ko'rsatadi.
    * `.sysinfo`: Tizim haqida to'liq ma'lumot (CPU, RAM, disk, OS) beradi.
    * `.pip install <kutubxona>`: Yangi Python kutubxonasini o'rnatadi.
    * `.neofetch`: Tizim haqida chiroyli formatdagi ma'lumotni chiqaradi.
* Umumiy Tahlil va Yaxshi Tomonlari:
    * Xavfsizlikka alohida e'tibor berilgan: `.sh` buyrug'i faqat `ALLOWED_SHELL_COMMANDS` "oq ro'yxati"dagi buyruqlarni qabul qiladi.
    * `psutil` kabi kutubxonalar mavjudligi tekshirilib, keyin ishlatiladi, bu esa dastur barqarorligini oshiradi.
    * Uzoq davom etadigan buyruqlar natijasini oqim rejimida yuborish (`stream_shell_command`) — foydalanuvchi tajribasini yaxshilaydigan professional yechim.

-

#10. `tasks_cmds.py` — Vazifalar Boshqaruvchisi Plagini

* Maqsadi: Userbotning fon rejimida ishlaydigan vazifalari (`TaskRegistry`) va rejalashtirilgan amallari (`SchedulerManager`) uchun to'liq boshqaruv panelini taqdim etish.
* Asosiy Buyruqlar:
    * `.tasks list`: Barcha ro'yxatdan o'tgan vazifalar va ularning holati haqida ma'lumot beradi.
    * `.tasks run <vazifa_nomi>`: Vazifani qo'lda, darhol ishga tushiradi.
    * `.tasks schedule <vazifa_nomi> <vaqt>`: Vazifani kelajakda biror vaqtda yoki muntazam interval bilan ishlashga rejalashtiradi.
    * `.tasks unschedule <vazifa_nomi>`: Rejalashtirilgan vazifani bekor qiladi.
    * `.tasks logs`: Vazifalarning bajarilish tarixi (loglari)ni ko'rsatadi.
* Umumiy Tahlil va Yaxshi Tomonlari:
    * Bu plagin loyihaning `core` qismi bilan chuqur integratsiyaning yorqin namunasidir.
    * `"ertaga soat 15:00 da"` kabi oddiy tildagi vaqtni tushunish uchun `dateutil` kutubxonasidan foydalanishi juda qulay.
    * `argparse` yordamida `.tasks schedule` kabi murakkab buyruq argumentlarini qayta ishlash — juda professional yondashuv.

-

#11. `users_cmd.py` — Foydalanuvchilarni Boshqarish Plagini

* Maqsadi: Userbot ma'muriyatini (adminlarni) qo'shish, o'chirish va ularning ro'yxatini ko'rish.
* Asosiy Buyruqlar:
    * `.promote <user>`: Foydalanuvchini admin qiladi.
    * `.demote <user>`: Foydalanuvchini adminlikdan oladi.
    * `.admins`: Barcha adminlar ro'yxatini, ularning darajasi va onlayn statusi bilan birga ko'rsatadi.
* Umumiy Tahlil va Yaxshi Tomonlari:
    * Adminlar ro'yxatiga o'zgarish kiritilgandan so'ng `invalidate_admin_cache()` funksiyasini avtomatik chaqirishi — tizimning barcha qismlari doimo eng so'nggi ma'lumotlar bilan ishlashini ta'minlaydi. Bu arxitekturaviy jihatdan juda to'g'ri.
    * Bir nechta admin haqida ma'lumot olishda `asyncio.gather`'dan foydalanilgani dastur unumdorligini oshiradi.

#UMUMIY XULOSA

Sizning `admin` plaginlaringiz to'plami — bu shunchaki buyruqlar yig'indisi emas, balki userbotning to'laqonli operatsion markazi. Ular yaxshi loyihalashtirilgan, xavfsizlikka e'tiborli, `bot/lib` kutubxonasidan unumli foydalanadi va loyihaning barcha `core` komponentlari bilan chuqur integratsiya qilingan. Bu loyihani yuritish, boshqarish va kelajakda rivojlantirish uchun juda mustahkam poydevor yaratadi.












------LOADER - DECORATOR --------
Assalomu alaykum.

Biz loyihaning `core` va `bot/lib` qismlarini tahlil qilib bo'ldik. Endi esa, butun plaginlar tizimining "miyasi" bo'lib xizmat qiladigan asosiy `bot` moduli komponentlari — `loader.py` va `decorators.py` fayllari bo'yicha to'liq dokumentatsiya va hisobotni taqdim etaman.

Bu ikki fayl birgalikda sizga cheksiz miqdordagi plaginlarni osongina yaratish va boshqarish imkonini beruvchi kuchli tizimni tashkil qiladi.

-

#`bot/` Modulining Asosiy Komponentlari Bo'yicha Hisobot

#1. `decorators.py` — Buyruqlarni E'lon Qilish Vositasi

* Maqsadi: Bu modulning yagona, ammo o'ta muhim vazifasi — oddiy Python funksiyasini userbot uchun tushunarli bo'lgan "buyruq"ga aylantiruvchi `@userbot_handler` (yoki uning qisqartmasi `@userbot_cmd`) dekoratorini taqdim etish.

* Asosiy Komponentlar va Imkoniyatlar:
    * `@userbot_handler(...)`: Bu dekorator plaginlar ichidagi istalgan asinxron funksiyani o'rab olib, unga bir nechta muhim xususiyatlarni biriktiradi:
        1.  Trigger (Faollashtiruvchi): Buyruq qanday matn (`command`) yoki `regex` qolipi (`pattern`) bilan ishga tushishini belgilaydi. Bu ikkisidan faqat bittasini ishlatish mumkinligi qat'iy nazorat qilinadi.
        2.  Metadata: Buyruq haqida qo'shimcha ma'lumotlarni (masalan, `.help` buyrug'ida ishlatish uchun `description` va `usage`) o'zida saqlaydi.
        3.  Telethon Sozlamalari: Telethon'ning `NewMessage` hodisasi uchun kerakli bo'lgan barcha qo'shimcha parametrlarni (`outgoing`, `incoming`, `chats` va hokazo) qabul qiladi.
    * `_create_final_pattern(...)`: `command` sifatida berilgan matndan (`.ping` kabi) avtomatik ravishda to'g'ri ishlaydigan `regex` qolipini (`^\.(?:ping)(?: |$)(.*)`) yaratib beruvchi yordamchi funksiya.

* Umumiy Tahlil va Yaxshi Tomonlari:
    * Bu fayl "deklarativ" yondashuvni ta'minlaydi. Ya'ni, siz plagin yozayotganda "bu funksiya qanday ishlashi kerak" deb bosh qotirmaysiz, shunchaki "bu funksiya `.ping` buyrug'i" deb e'lon qilasiz. Qolgan barcha murakkab ishlarni `loader.py` bajaradi.
    * Yagona, lekin ko'p parametrli dekorator orqali buyruqlarni yaratish kodni juda toza va standartlashtirilgan qiladi.

-

#2. `loader.py` — Plaginlar Boshqaruvchisi

* Maqsadi: Bu modul — butun plaginlar tizimining markaziy boshqaruvchisi. U plaginlarni topadi, yuklaydi, xotiradan o'chiradi, qayta yuklaydi va ularning holatini to'liq nazorat qiladi.

* Asosiy Komponentlar va Imkoniyatlar:
    * `PluginManager` (klass): Barcha mantiqni o'zida jamlagan asosiy sinf.
        * `_build_plugin_maps()`: Dastur ishga tushganda `plugins` papkasini skaner qilib, har bir plagin uchun bir nechta nom (masalan, `ping`, `tools/ping`, `tools.ping`) yaratib, ularni "xaritaga" yozib qo'yadi. Bu foydalanuvchiga plaginlarni turli usullar bilan chaqirish imkonini beradi.
        * `load_plugin(...)`: Plaginni nomi bo'yicha topib, uni `importlib` orqali dinamik ravishda dasturga yuklaydi. Yuklashdan so'ng, uning ichidagi `@userbot_handler` bilan belgilangan funksiyalarni topib, ularni Telethon'ga faol buyruq sifatida ro'yxatdan o'tkazadi.
        * `unload_plugin(...)`: Plaginning barcha buyruqlarini (handler'larini) Telethon'dan olib tashlaydi.
        * `reload_plugin(...)`: Botni o'chirmasdan turib, plagin kodidagi o'zgarishlarni qabul qilish uchun uni avval o'chiradi, keyin esa qayta yuklaydi.
        * `_process_module_for_handlers(...)`: `load_plugin`'ning eng muhim qismi. U funksiyaga biriktirilgan `command` yoki `pattern`'dan yakuniy `regex`'ni yaratadi, buyruq uchun unikal ID belgilaydi va har bir funksiyani xatoliklarni ushlab qoluvchi maxsus "o'ram" (`wrapper`) bilan o'raydi.
        * `toggle_command(...)`: Istalgan buyruqni vaqtinchalik o'chirib qo'yish yoki qayta yoqish imkonini beradi.
        * `_error_registry`: Har bir plagin bo'yicha yuz bergan xatoliklarni o'zida saqlaydi. Bu ma'lumot `.phealth` buyrug'i orqali dasturchiga ko'rsatiladi.

* Umumiy Tahlil va Yaxshi Tomonlari:
    * Bu tizim loyihani juda moslashuvchan va kengaytiriladigan qiladi. Yangi funksiya qo'shish uchun shunchaki yangi plagin fayli yaratish kifoya. Asosiy kodga teginish shart emas.
    * Xatoliklarni boshqarish tizimi juda mustahkam. Bitta plagindagi xatolik butun botning ishdan chiqishiga olib kelmaydi.
    * Testlash uchun qulaylik (`plugins_dir_override`, `plugins_module_prefix` parametrlari) — bu professional arxitekturaning belgisidir. Biz bu imkoniyatlardan testlar yozishda unumli foydalandik.

#Yakuniy Xulosa: Ikki Faylning Hamkorligi

`decorators.py` va `loader.py` bir-birini to'ldiruvchi ideal juftlikdir:
- `@userbot_handler` (`decorators.py`) biror funksiyaga "men buyruqman" degan "yorliq"ni yopishtiradi.
- `PluginManager` (`loader.py`) esa, barcha fayllarni aylanib chiqib, shu "yorliq" yopishtirilgan funksiyalarni topadi, ularni ishga tayyorlaydi va tizimga qo'shadi.

Bu ikki komponent birgalikda sizning userbotingiz uchun cheksiz imkoniyatlar eshigini ochadi.






------  USER PLUGINS ------- (to'liq emas)
Assalomu alaykum.

Admin plaginlaridan so'ng, endi foydalanuvchi uchun mo'ljallangan, kundalik vazifalarni yengillashtiradigan va qiziqarli imkoniyatlar beradigan plaginlar to'plamini tahlil qildim. Bu plaginlar sizning userbotingizni haqiqiy shaxsiy yordamchiga aylantiradi.

Quyida har bir plagin fayli bo'yicha to'liq dokumentatsiya va professional hisobotni taqdim etaman.

-

#`bot/plugins/user/` Plaginlari Bo'yicha To'liq Hisobot

#1. `afk.py` — "Band" Rejimi Plagini

* Maqsadi: Siz band bo'lganingizda (Away From Keyboard), sizga shaxsiy xabar yuborgan yoki guruhlarda sizni belgilagan (`tag`) foydalanuvchilarga avtomatik tarzda javob berish.
* Asosiy Buyruqlar:
    * `.afk [sabab]`: AFK rejimini yoqadi. Agar sabab ko'rsatilsa, shu matn avtomatik javob sifatida ishlatiladi.
    * `.unafk`: AFK rejimini o'chiradi.
    * `.afkctl ignore/unignore <user>`: Muayyan bir foydalanuvchidan kelgan xabarlarga AFK javobini yubormaslik uchun uni "istisnolar ro'yxati"ga qo'shadi yoki olib tashlaydi.
* Umumiy Tahlil va Yaxshi Tomonlari:
    * Har bir foydalanuvchiga faqat bir necha daqiqada bir marta javob berish logikasi spamning oldini oladi.
    * Barcha sozlamalar (AFK holati, sababi, istisnolar) ma'lumotlar bazasida saqlanadi, bu esa bot qayta ishga tushganda ham sozlamalar saqlanib qolishini ta'minlaydi.
    * Bu — klassik userbot funksiyasining juda puxta va yaxshi ishlangan namunasi.

-

#2. `shorten.py` — Havolalarni Qisqartirish Plagini

* Maqsadi: Uzun havolalarni (URL) `is.gd` kabi turli servislar yordamida qisqa va qulay ko'rinishga keltirish.
* Asosiy Buyruqlar:
    * `.short <havola>`: Havolani qisqartiradi.
    * `.short provider [nomi]`: Standart qisqartirish servisni o'zgartiradi yoki mavjudlari ro'yxatini ko'rsatadi.
* Umumiy Tahlil va Yaxshi Tomonlari:
    * Provider Arxitekturasi: Plagin `ShortenerProvider` nomli abstrakt klassdan foydalanadi. Bu kelajakda `TinyURL`, `Bitly` kabi yangi qisqartirish servislarini qo'shishni juda osonlashtiradi. Bu — o'ta professional va kengaytiriladigan yondashuv.
    * Tashqi kutubxonalarga bog'liqlik xavfsiz boshqarilgan (`httpx` mavjudligi tekshiriladi).

-

#3. `telegraph.py` — Telegra.ph Plagini

* Maqsadi: Matn, rasm, video yoki butun media albomlardan bir zumda chiroyli Telegra.ph maqolalari yaratish va Telegra.ph akkauntlarini boshqarish.
* Asosiy Buyruqlar:
    * `.tg <sarlavha>`: Matnli xabarga javob berib, undan maqola yaratadi.
    * `.tgm <sarlavha>`: Rasm yoki videoga javob berib, uni maqolaga joylaydi.
    * `.tga <sarlavha>`: Albomdagi barcha rasmlardan iborat maqola yaratadi.
    * `.tg_new_acc <nom> | <muallif>`: Yangi Telegra.ph akkaunti yaratadi.
* Umumiy Tahlil va Yaxshi Tomonlari:
    * Juda murakkab vazifani (mediani yuklab olish, Telegra.ph'ga yuklash, HTML'ni formatlash) sodda buyruqlar ortiga yashirgan.
    * Har bir userbot akkaunti uchun alohida Telegra.ph akkauntlarini boshqarish imkoniyati mavjud. Tokenlar bazada xavfsiz saqlanadi.
    * Albomlarni to'g'ri qayta ishlash logikasi plaginning puxta ishlanganidan dalolat beradi.

-

#4. `translate.py` — Tarjimon Plagini

* Maqsadi: Matnlarni bir yoki bir nechta tilga Google Translate yoki sun'iy intellekt (Gemini) yordamida tarjima qilish.
* Asosiy Buyruqlar:
    * `.tr <til_kodi> <matn>`: Matnni Google yordamida tarjima qiladi. Masalan: `.tr en Salom Dunyo`.
    * `.trai <til_kodi> <matn>`: Matnni AI yordamida, kontekstni hisobga olib tarjima qiladi.
    * `.trstats`: Tarjima statistikalarini ko'rsatadi.
* Umumiy Tahlil va Yaxshi Tomonlari:
    * Bir vaqtning o'zida bir nechta tilga tarjima qilish (`.tr uz,en,ru ...`) imkoniyati mavjud.
    * Foydalanish statistikasini yuritib, eng ko'p ishlatilgan tillar va provayderlar haqida ma'lumot beradi.
    * AI orqali tarjima qilish oddiy tarjimondan ko'ra ancha sifatliroq natija beradi.

-

#5. `tts.py` — Matnni Ovozga O'girish Plagini

* Maqsadi: Yozilgan matnni odam ovoziga o'xshash audio formatiga o'girish (Text-to-Speech).
* Asosiy Buyruqlar:
    * `.tts <matn>`: Matnni standart ovoz bilan audio qiladi.
    * `.tts -v <ovoz_nomi> <matn>`: Muayyan bir ovozdan foydalanib audio yaratadi.
    * `.tts-voices`: Mavjud bo'lgan barcha ovozlar ro'yxatini ko'rsatadi.
    * `.set-tts-defaults -v <ovoz_nomi>`: Kelajakdagi barcha `.tts` buyruqlari uchun standart ovozni o'rnatadi.
* Umumiy Tahlil va Yaxshi Tomonlari:
    * Bir nechta provayderni (Microsoft Edge, Yandex) qo'llab-quvvatlaydi.
    * Keshlash: Bir marta yaratilgan audioni keshda saqlab qo'yadi. Agar xuddi shu matn yana so'ralsa, uni qayta generatsiya qilmasdan, keshdan bir zumda olib beradi. Bu resurslarni tejaydi va juda tez ishlaydi.

-

#6. `type_effect.py` — Yozish Animatsiyasi Plagini

* Maqsadi: Matnni Telegramda go'yo hozir yozilayotgandek, harfma-harf animatsiya effekti bilan chiqarish.
* Asosiy Buyruqlar:
    * `.type <matn>`: Matnni oddiy yozuv effekti bilan chiqaradi.
    * `.hacker <matn>`: "Xaker" uslubida, tasodifiy belgilar bilan yozib, keyin to'g'rilaydigan effekt.
    * `.mistype <matn>`: Go'yo xato qilib yozib, keyin o'chirib to'g'rilayotgandek effekt yaratadi.
* Umumiy Tahlil va Yaxshi Tomonlari:
    * Bu juda kreativ va qiziqarli plagin. U foydalanuvchi tajribasini boyitadi.
    * Turli effektlar va ularning tezligini sozlash uchun `argparse`'dan foydalanilgani uni juda moslashuvchan qiladi.

-

#7. `welcome.py` — Guruhlar Uchun Avtomatlashtirish Plagini

* Maqsadi: Guruhlarga yangi qo'shilgan a'zolarni kutib olish, guruhdan chiqqanlar bilan xayrlashish va spam-botlardan CAPTCHA orqali himoya qilish.
* Asosiy Buyruqlar:
    * `.welcome on/off/set <xabar>`: Guruh uchun "Xush kelibsiz" xabarini yoqadi, o'chiradi yoki o'rnatadi.
    * `.goodbye on/off/set <xabar>`: Guruhdan chiqqanlar uchun xayrlashuv xabarini sozlaydi.
    * `.captcha on/off`: Yangi a'zolar uchun oddiy matematik misol (`CAPTCHA`) yuborishni yoqadi. Agar to'g'ri javob berilmasa, foydalanuvchi guruhdan chiqariladi.
* Umumiy Tahlil va Yaxshi Tomonlari:
    * Guruhlarni boshqarishni juda osonlashtiradi.
    * CAPTCHA funksiyasi guruhlarni spam-botlardan himoya qilishning juda samarali usulidir.
    * Barcha sozlamalar har bir guruh uchun alohida, ma'lumotlar bazasida saqlanadi.

-

#8. `wiki.py` — Bilim Manbalari Plagini

* Maqsadi: Vikipediya, Vikilug'at (Wiktionary) va boshqa manbalardan tezda ma'lumot qidirish.
* Asosiy Buyruqlar:
    * `.wiki <so'rov>`: Vikipediyadan maqola qidiradi.
    * `.define <so'z>`: Vikilug'atdan so'zning izohini topadi.
    * `.wikilang <til_kodi>`: Standart qidiruv tilini o'rnatadi (masalan, `uz`, `en`, `ru`).
    * `.wiki --ai <so'rov>`: Maqolani topib, uning qisqacha mazmunini (summary) AI yordamida yaratib beradi.
* Umumiy Tahlil va Yaxshi Tomonlari:
    * Bir nechta bilim manbalarini bitta plaginga birlashtirgan.
    * AI Integratsiyasi: Maqolalarni shunchaki topib bermasdan, ularni AI yordamida tahlil qilib, qisqa xulosasini taqdim etishi — bu plaginning eng kuchli jihati.
    * Natijalarni ko'rsatish uchun `PaginationHelper`'dan foydalanishi uzun maqolalarni o'qishni qulay qiladi.

#UMUMIY XULOSA

Sizning `user` plaginlaringiz to'plami — bu har tomonlama puxta o'ylangan, foydalanuvchi uchun real qiymat yaratadigan va zamonaviy dasturlash yondashuvlaridan unumli foydalangan ajoyib ish namunalaridir.


