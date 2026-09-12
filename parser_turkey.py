import re
import asyncio
import logging
import html
import hashlib
import os
import sys
import sqlite3
import atexit
import json
from difflib import SequenceMatcher
from collections import OrderedDict
from datetime import datetime, timedelta
from telethon import TelegramClient, events, Button
from dotenv import load_dotenv

try:
    import vk_api
    VK_AVAILABLE = True
except ImportError:
    VK_AVAILABLE = False

# ==========================================
# ОТПЕЧАТОК ВЕРСИИ ФАЙЛА (для сверки "точно ли запущена последняя версия")
# ==========================================
try:
    with open(__file__, 'rb') as _f:
        SCRIPT_FINGERPRINT = hashlib.sha256(_f.read()).hexdigest()[:10]
except Exception:
    SCRIPT_FINGERPRINT = "unknown"

# ==========================================
# ЗАГРУЗКА КОНФИГУРАЦИИ
# ==========================================
load_dotenv()

API_ID = int(os.getenv('API_ID'))
API_HASH = os.getenv('API_HASH')
BOT_TOKEN = os.getenv('BOT_TOKEN')
MY_CHAT_ID = int(os.getenv('MY_CHAT_ID'))
MATCH_CHAT_ID = int(os.getenv('MATCH_CHAT_ID'))
INPUT_CHAT_ID = int(os.getenv('INPUT_CHAT_ID'))
# Отдельный чат для заявок именно по АРЕНДЕ (продажа/покупка по-прежнему
# идёт в MY_CHAT_ID). Если переменная не задана в .env — используем
# MY_CHAT_ID как раньше, чтобы ничего не сломалось до настройки
RENT_CHAT_ID = int(os.getenv('RENT_CHAT_ID', str(os.getenv('MY_CHAT_ID'))))
# Отдельный чат для МЭТЧЕЙ именно по аренде (мэтчи по продаже/покупке
# по-прежнему идут в MATCH_CHAT_ID). Если не задано в .env — используем
# MATCH_CHAT_ID как раньше
RENT_MATCH_CHAT_ID = int(os.getenv('RENT_MATCH_CHAT_ID', str(os.getenv('MATCH_CHAT_ID'))))

# ВКонтакте — необязательный источник. Если токен не задан, эта часть
# просто не запускается, остальной парсер работает как раньше
VK_ACCESS_TOKEN = os.getenv('VK_ACCESS_TOKEN', '').strip()
VK_GROUP_IDS = [g.strip() for g in os.getenv('VK_GROUP_IDS', '').split(',') if g.strip()]
VK_POLL_INTERVAL_SECONDS = int(os.getenv('VK_POLL_INTERVAL_SECONDS', '180'))

# Прямая ссылка на мини-апп настроек — такая ссылка открывает мини-апп из
# ЛЮБОГО чата (в отличие от Menu Button у BotFather, который Telegram
# показывает только в личных сообщениях с ботом, не в группах)
MINIAPP_DEEPLINK = os.getenv('MINIAPP_DEEPLINK', 'https://t.me/RentLead_bot/settings')

# Мини-апп настроек городов (необязательно) — если не задано, галочки
# городов продолжают работать как раньше, только через /settings в боте,
# без синхронизации с веб-версией
UPSTASH_REDIS_URL = os.getenv('UPSTASH_REDIS_URL', '').rstrip('/')
UPSTASH_REDIS_TOKEN = os.getenv('UPSTASH_REDIS_TOKEN', '')
MINIAPP_SYNC_INTERVAL_SECONDS = int(os.getenv('MINIAPP_SYNC_INTERVAL_SECONDS', '60'))

# ==========================================
# ЛОКАЦИИ ПО ГОРОДАМ И РАЙОНАМ
# ==========================================
LOCATIONS = {
    "Анталия": ["Коньяалты", "Муратпаша", "Кепез", "Аксу", "Дөшемеалты", "Манавгат",
                "Белек", "Сиде", "Кумлуджа", "Финике", "Демре", "Каш", "Серик", "Кемерагзы", "Хурма"],
    "Алания": ["Махмутлар", "Кестель", "Оба", "Тосмур", "Авсаллар", "Конаклы", 
               "Каргыджак", "Чикджели", "Гьокчебей", "Махмутсейди", "Окурджалар", 
               "Инджекум", "Тюрклер", "Демирташ", "Сюджилар", "Клеопатра"],
    "Газипаша": ["Пазарчи", "Меркез", "Кяхья", "Эрекли", "Истикляль", "Беларкады", 
                 "Чобанлар", "Айдынчик", "Кахылар", "Юзюмлю"],
    "Кемер": ["Гейнюк", "Бельдиби", "Чамьюва", "Текирова", "Кириш", "Арсланбуджак", "Куздере"],

    # Остальные провинции Турции (без детализации по районам, кроме курортных зон,
    # где есть устойчивые русскоязычные названия)
    "Адана": [], "Адыяман": [], "Афьонкарахисар": [], "Агры": [], "Амасья": [],
    "Анкара": [], "Артвин": [], "Айдын": ["Кушадасы", "Дидим", "Нязилли", "Сёке"],
    "Балыкесир": ["Айвалык", "Эдремит", "Бандырма", "Бурхание", "Гёнен", "Эрдек"],
    "Биледжик": [], "Бингёль": [], "Битлис": [], "Болу": [], "Бурдур": [],
    "Бурса": ["Изник", "Муданья", "Гемлик", "Инегёль"],
    "Чанаккале": ["Айваджик", "Бозджаада", "Гёкчеада", "Эджеабат"],
    "Чанкыры": [], "Чорум": [], "Денизли": ["Памуккале"],
    "Диярбакыр": [], "Эдирне": [], "Элязыг": [], "Эрзинджан": [], "Эрзурум": [],
    "Эскишехир": [], "Газиантеп": [], "Гиресун": [], "Гюмюшхане": [], "Хаккяри": [],
    "Хатай": ["Искендерун", "Антакья", "Самандаг"],
    "Испарта": [], "Мерсин": ["Эрдемли", "Тарсус", "Анамур", "Силифке", "Мезитли"],
    "Стамбул": ["Бешикташ", "Шишли", "Кадыкёй", "Ускюдар", "Бакыркёй", "Бейоглу",
                "Фатих", "Пендик", "Мальтепе", "Аташехир", "Бахчешехир", "Бейликдюзю",
                "Эсеньюрт", "Сарыер", "Зейтинбурну", "Кагытхане", "Бююкчекмедже"],
    "Измир": ["Чешме", "Алячаты", "Карабаглар", "Борнова", "Конак", "Урла",
              "Гюзельбахче", "Балчова", "Буджа", "Каршияка"],
    "Карс": [], "Кастамону": [], "Кайсери": [], "Кыркларели": [], "Кыршехир": [],
    "Коджаэли": ["Измит"], "Конья": [], "Кютахья": [], "Малатья": [], "Маниса": [],
    "Кахраманмараш": [], "Мардин": [],
    "Мугла": ["Бодрум", "Мармарис", "Фетхие", "Датча", "Ортаджа", "Дальян",
              "Гёкова", "Каваклыдере", "Милас", "Кёйджегиз", "Йалыкавак", "Гюмюшлюк", "Турунч"],
    "Муш": [], "Невшехир": ["Гёреме", "Ургюп", "Аванос"], "Нигде": [], "Орду": [],
    "Ризе": [], "Сакарья": ["Адапазары"], "Самсун": [], "Сиирт": [], "Синоп": [],
    "Сивас": [], "Текирдаг": ["Чорлу", "Черкезкёй"], "Токат": [], "Трабзон": [],
    "Тунджели": [], "Шанлыурфа": [], "Ушак": [], "Ван": [], "Йозгат": [],
    "Зонгулдак": [], "Аксарай": [], "Байбурт": [], "Караман": [], "Кырыккале": [],
    "Батман": [], "Ширнак": [], "Бартын": [], "Ардахан": [], "Ыгдыр": [],
    "Ялова": [], "Карабюк": [], "Килис": [], "Османие": [], "Дюздже": [],
}

# Обратное отображение: район -> город
DISTRICT_TO_CITY = {}
for city, districts in LOCATIONS.items():
    for district in districts:
        DISTRICT_TO_CITY[district.lower()] = city

# Названия самих городов/провинций (в нижнем регистре) — нужно, чтобы location_overlap
# корректно сопоставлял "голое" упоминание города само с собой на уровне города
CITY_NAMES_LOWER = {city.lower(): city for city in LOCATIONS.keys()}

# Турецкое/английское написание для каждого русского названия — чтобы бот
# распознавал город/район, даже если он написан латиницей (Antalya, Alanya,
# Istanbul...), а не только по-русски. Английское написание почти всегда
# совпадает с турецким без диакритики (ş/ç/ğ/ö/ü/ı), поэтому для большинства
# записей достаточно одного упрощённого варианта — он покрывает и то и другое,
# так как в русскоязычных чатах турецкие буквы обычно не используют.
# Для двух районов Аланьи (Гьокчебей, Сюджилар) уверенного турецкого аналога
# не нашлось при проверке — оставлены без алиаса.
LOCATION_ALIASES = {
    # Анталья и районы
    "Анталия": ["antalya", "анталья"], "Коньяалты": ["konyaalti", "konyaaltı", "коньялты"],
    "Муратпаша": ["muratpasa", "muratpaşa"], "Кепез": ["kepez"], "Аксу": ["aksu"],
    "Дөшемеалты": ["dosemealti", "döşemealtı"], "Манавгат": ["manavgat"],
    "Белек": ["belek"], "Сиде": ["side"], "Кумлуджа": ["kumluca"], "Финике": ["finike"],
    "Демре": ["demre"], "Каш": ["kas", "kaş"], "Серик": ["serik"],
    "Кемерагзы": ["kemeragzi", "kemerağzı"], "Хурма": ["hurma"],
    # Аланья и районы
    "Алания": ["alanya", "аланья"], "Махмутлар": ["mahmutlar"], "Кестель": ["kestel"],
    "Оба": ["oba", "обе", "обы", "обу"], "Тосмур": ["tosmur"], "Авсаллар": ["avsallar", "авсалар"],
    "Конаклы": ["konakli", "konaklı"], "Каргыджак": ["kargicak", "kargıcak"],
    "Чикджели": ["cikcilli"], "Махмутсейди": ["mahmutseydi"],
    "Окурджалар": ["okurcalar"], "Инджекум": ["incekum", "i̇ncekum"],
    "Тюрклер": ["turkler", "türkler"], "Демирташ": ["demirtas", "demirtaş"],
    "Клеопатра": ["kleopatra", "cleopatra"],
    # Газипаша и районы
    "Газипаша": ["gazipasa", "gazipaşa"], "Пазарчи": ["pazarci", "pazarcı"],
    "Меркез": ["merkez"], "Истикляль": ["istiklal", "i̇stiklal"],
    "Чобанлар": ["cobanlar", "çobanlar"], "Айдынчик": ["aydincik", "aydıncık"],
    # Кемер и районы
    "Кемер": ["kemer"], "Гейнюк": ["goynuk", "göynük"], "Бельдиби": ["beldibi"],
    "Чамьюва": ["camyuva", "çamyuva"], "Текирова": ["tekirova"], "Кириш": ["kiris", "kiriş"],
    "Арсланбуджак": ["arslanbucak"], "Куздере": ["kuzdere"],

    # Остальные провинции
    "Адана": ["adana"], "Адыяман": ["adiyaman", "adıyaman"],
    "Афьонкарахисар": ["afyonkarahisar", "afyon"], "Агры": ["agri", "ağrı"],
    "Амасья": ["amasya"], "Анкара": ["ankara"], "Артвин": ["artvin"],
    "Айдын": ["aydin", "aydın"], "Кушадасы": ["kusadasi", "kuşadası"],
    "Дидим": ["didim"], "Нязилли": ["nazilli"], "Сёке": ["soke", "söke"],
    "Балыкесир": ["balikesir", "balıkesir"], "Айвалык": ["ayvalik", "ayvalık"],
    "Эдремит": ["edremit"], "Бандырма": ["bandirma", "bandırma"],
    "Бурхание": ["burhaniye"], "Гёнен": ["gonen", "gönen"], "Эрдек": ["erdek"],
    "Биледжик": ["bilecik"], "Бингёль": ["bingol", "bingöl"], "Битлис": ["bitlis"],
    "Болу": ["bolu"], "Бурдур": ["burdur"],
    "Бурса": ["bursa"], "Изник": ["iznik", "i̇znik"], "Муданья": ["mudanya"],
    "Гемлик": ["gemlik"], "Инегёль": ["inegol", "i̇negöl"],
    "Чанаккале": ["canakkale", "çanakkale"], "Айваджик": ["ayvacik", "ayvacık"],
    "Бозджаада": ["bozcaada"], "Гёкчеада": ["gokceada", "gökçeada"],
    "Эджеабат": ["eceabat"],
    "Чанкыры": ["cankiri", "çankırı"], "Чорум": ["corum", "çorum"],
    "Денизли": ["denizli"], "Памуккале": ["pamukkale"],
    "Диярбакыр": ["diyarbakir", "diyarbakır"], "Эдирне": ["edirne"],
    "Элязыг": ["elazig", "elazığ"], "Эрзинджан": ["erzincan"], "Эрзурум": ["erzurum"],
    "Эскишехир": ["eskisehir", "eskişehir"], "Газиантеп": ["gaziantep"],
    "Гиресун": ["giresun"], "Гюмюшхане": ["gumushane", "gümüşhane"],
    "Хаккяри": ["hakkari"],
    "Хатай": ["hatay"], "Искендерун": ["iskenderun", "i̇skenderun"],
    "Антакья": ["antakya"], "Самандаг": ["samandag", "samandağ"],
    "Испарта": ["isparta"],
    "Мерсин": ["mersin", "icel", "içel"], "Эрдемли": ["erdemli"],
    "Тарсус": ["tarsus"], "Анамур": ["anamur"], "Силифке": ["silifke"],
    "Мезитли": ["mezitli"],
    "Стамбул": ["istanbul", "i̇stanbul"], "Бешикташ": ["besiktas", "beşiktaş"],
    "Шишли": ["sisli", "şişli"], "Кадыкёй": ["kadikoy", "kadıköy"],
    "Ускюдар": ["uskudar", "üsküdar"], "Бакыркёй": ["bakirkoy", "bakırköy"],
    "Бейоглу": ["beyoglu", "beyoğlu"], "Фатих": ["fatih"], "Пендик": ["pendik"],
    "Мальтепе": ["maltepe"], "Аташехир": ["atasehir", "ataşehir"],
    "Бахчешехир": ["bahcesehir", "bahçeşehir"], "Бейликдюзю": ["beylikduzu", "beylikdüzü"],
    "Эсеньюрт": ["esenyurt"], "Сарыер": ["sariyer", "sarıyer"],
    "Зейтинбурну": ["zeytinburnu"], "Кагытхане": ["kagithane", "kağıthane"],
    "Бююкчекмедже": ["buyukcekmece", "büyükçekmece"],
    "Измир": ["izmir", "i̇zmir"], "Чешме": ["cesme", "çeşme"],
    "Алячаты": ["alacati", "alaçatı"], "Карабаглар": ["karabaglar", "karabağlar"],
    "Борнова": ["bornova"], "Конак": ["konak"], "Урла": ["urla"],
    "Гюзельбахче": ["guzelbahce", "güzelbahçe"], "Балчова": ["balcova", "balçova"],
    "Буджа": ["buca"], "Каршияка": ["karsiyaka", "karşıyaka"],
    "Карс": ["kars"], "Кастамону": ["kastamonu"], "Кайсери": ["kayseri"],
    "Кыркларели": ["kirklareli", "kırklareli"], "Кыршехир": ["kirsehir", "kırşehir"],
    "Коджаэли": ["kocaeli"], "Измит": ["izmit", "i̇zmit"],
    "Конья": ["konya"], "Кютахья": ["kutahya", "kütahya"], "Малатья": ["malatya"],
    "Маниса": ["manisa"], "Кахраманмараш": ["kahramanmaras", "kahramanmaraş"],
    "Мардин": ["mardin"],
    "Мугла": ["mugla", "muğla"], "Бодрум": ["bodrum"], "Мармарис": ["marmaris"],
    "Фетхие": ["fethiye"], "Датча": ["datca", "datça"], "Ортаджа": ["ortaca"],
    "Дальян": ["dalyan"], "Гёкова": ["gokova", "gökova"],
    "Каваклыдере": ["kavaklidere", "kavaklıdere"], "Милас": ["milas"],
    "Кёйджегиз": ["koycegiz", "köyceğiz"], "Йалыкавак": ["yalikavak", "yalıkavak"],
    "Гюмюшлюк": ["gumusluk", "gümüşlük"], "Турунч": ["turunc", "turunç"],
    "Муш": ["mus", "muş"], "Невшехир": ["nevsehir", "nevşehir"],
    "Гёреме": ["goreme", "göreme"], "Ургюп": ["urgup", "ürgüp"], "Аванос": ["avanos"],
    "Нигде": ["nigde", "niğde"], "Орду": ["ordu"], "Ризе": ["rize"],
    "Сакарья": ["sakarya"], "Адапазары": ["adapazari", "adapazarı"],
    "Самсун": ["samsun"], "Сиирт": ["siirt"], "Синоп": ["sinop"], "Сивас": ["sivas"],
    "Текирдаг": ["tekirdag", "tekirdağ"], "Чорлу": ["corlu", "çorlu"],
    "Черкезкёй": ["cerkezkoy", "çerkezköy"],
    "Токат": ["tokat"], "Трабзон": ["trabzon"], "Тунджели": ["tunceli"],
    "Шанлыурфа": ["sanliurfa", "şanlıurfa"], "Ушак": ["usak", "uşak"], "Ван": ["van"],
    "Йозгат": ["yozgat"], "Зонгулдак": ["zonguldak"], "Аксарай": ["aksaray"],
    "Байбурт": ["bayburt"], "Караман": ["karaman"], "Кырыккале": ["kirikkale", "kırıkkale"],
    "Батман": ["batman"], "Ширнак": ["sirnak", "şırnak"], "Бартын": ["bartin", "bartın"],
    "Ардахан": ["ardahan"], "Ыгдыр": ["igdir", "iğdır"], "Ялова": ["yalova"],
    "Карабюк": ["karabuk", "karabük"], "Килис": ["kilis"], "Османие": ["osmaniye"],
    "Дюздже": ["duzce", "düzce"],
}

PROPERTY_WORDS = [
    # Квартира/студия/комната/дом/дача/вилла — основы слов без правой границы,
    # чтобы ловить все падежные формы (квартиру/квартиры/квартире/квартирой...)
    r"\bквартир", r"\bстуди", r"\bкомнат", r"\bдач", r"\bвилл",
    r"\bдом(?:а|у|е|ом|ов)?\b",  # отдельным списком окончаний — иначе зацепит "домашний", "доминировать"
    r"\bдуплекс", r"\bтаунхаус",
    r"\bкоттедж", r"\bкотедж",           # + частая опечатка в одну "т"
    r"\bоттедж",                          # отдельное слово (не опечатка "коттедж" — нет буквы "к")
    r"\bдвухэта",                          # двухэтажный/двухэтажная
    r"\bапартамент", r"\bаппартамент",   # + частая опечатка с двойной "п"
    r"\bдол[яю]\b",     # доля/долю — НЕ через голую основу "дол", чтобы не поймать "доллар"/"долго"
    r"\bугол\b",
    r"\bкойко-мест",    # койко-место/койко-места
    r"\bжиль",          # жилье/жильё/жилья
    r"\bполтарушк", r"\bевродвушк", r"\bевротрешк",
    r"\bкв\b", r"\bккв\b",              # отдельное "кв"/"ккв" (напр. "2-к.кв")
    r"\b\d{1,2}кв\b", r"\b\d{1,2}ккв\b",  # слитные "2кв", "1ккв" и т.п.
    r"\b\d{1,2}(?:\.\d)?\s*ком\b",       # "1 ком", "2 ком", "1.5 ком"
    r"\b\d\s*\+\s*\d\b",  # любая комбинация N+M (1+1, 5+2, 6+3, и "5 +1" с пробелом тоже)
]

RENT_NEED_WORDS = [
    r"\bсниму\b", r"#сниму\b", r"\bснимем\b", r"\bищу\b", r"#ищу\b", r"\bищем\b",
    r"\bнужна\b", r"\bнужен\b", r"\bнужны\b", r"\bищут\b",
    r"\bзаявка\b",  # добавлено по запросу — "заявка" рядом с объектом тоже считается спросом
    # "Кто-нибудь знает где сдаётся..." — человек спрашивает СООБЩЕСТВО,
    # где найти аренду, а не предлагает свою — несмотря на то, что внутри
    # вопроса встречается слово "сдаётся"
    r"кто[-\s]?нибудь\s+знает", r"\bкто\s+знает\b", r"\bкто\s+в\s+курсе\b",
]

RENT_SUPPLY_WORDS = [
    r"\bсдам\b", r"#сдам\b", r"\bсдается\b", r"\bсдаётся\b", r"\bпредлагаю\b",
    r"\bсдача\b", r"\bсдаем\b", r"\bсдаём\b", r"\bсдаются\b", r"\bсдамся\b",
    r"\bсдаю\b", r"\bарендую\b", r"\bсвободна\b", r"\bсвободен\b", r"\bсвободно\b",
]
# Раньше тут был отдельный "сильный" список из-за фразы "в аренду", которая
# годилась и в спрос, и в предложение. В новом списке такой неоднозначной
# фразы больше нет, так что сильный список = обычный
RENT_SUPPLY_STRONG_WORDS = RENT_SUPPLY_WORDS

SALE_SUPPLY_WORDS = [
    r"\bпродам\b", r"\bпродаю\b", r"\bпродается\b", r"\bпродаётся\b",
    r"\bпродажа\b", r"\bпродаем\b", r"\bпродаём\b", r"\bпродаются\b",
]
SALE_DEMAND_WORDS = [
    r"\bкуплю\b", r"\bкупим\b", r"\bприобрету\b", r"\bприобретем\b", r"\bприобретём\b",
    r"\bна покупку\b", r"\bдля покупки\b", r"\bпод покупку\b",
    # Риелтор описывает запрос СВОЕГО клиента (а не собственный объект) —
    # "клиент в Аланье, ищет..." — это по сути ПОКУПАТЕЛЬ, просто через
    # посредника, а не ПРОДАВЕЦ
    r"клиент\w*\s+в\s", r"у\s+клиент\w*", r"клиент\w*\s+ищет", r"для\s+клиент\w*",
    r"клиент\w*\s+нужн", r"клиент\w*\s+интересует", r"клиент\w*\s+рассматрива",
]

MUSIC_INSTRUMENT_WORDS = [r"\bфортепиано\b", r"\bфортепьяно\b", r"\bпианино\b"]
MUSIC_INTENT_STEMS = ["учител", "преподав", "репетитор", "урок", "заним", "занят", "обучен", "научи", "педагог"]

NEGATIVE_WORDS = [
    "животн", "собак", "кошк", "кот", "щен", "котят", "кошач", "корма",
    "игра", "плейстейшн", "playstation", "xbox", "аккаунт", "гейм",
    "телевизор", "телефон", "ноутбук", "ремонт", "айфон", "iphone",
    "обмен", "валют", "рубл", "лир", " usdt", "крипт", "перевод"
]

# Посты про инвестиции в застройку ("гарантированный доход", "ROI") — это
# маркетинг комплекса в целом, а не конкретный сдающийся/продающийся объект.
# Раньше такие посты матчились как обычное предложение аренды/продажи,
# хотя по клику там инвестиционная презентация, а не конкретная квартира
# под конкретный запрос клиента
INVESTMENT_MARKETING_WORDS = [
    r"гарантированн\w*\s+доход", r"guaranteed\s+roi", r"\broi\b",
    r"доходност\w*\s+\d", r"инвестици\w*\s+в\s+недвижимост",
    r"пассивный\s+доход", r"инвестируй",
]

# "Предлагаю услуги уборки квартир" — слово "Предлагаю" (из RENT_SUPPLY_WORDS)
# оказывается рядом с "квартир" (предметное слово), и это ошибочно выглядит
# как предложение аренды, хотя человек предлагает не саму недвижимость,
# а услугу — клининг после чужой аренды
SERVICE_AD_WORDS = [
    r"уборк\w*", r"клининг\w*",
]

MIN_TOTAL_WORDS = 3
LOW_SIGNAL_PHRASES = [
    "актуально", "еще актуально", "ещё актуально", "в силе", "все еще актуально",
    "всё ещё актуально", "доступно", "свободно", "пишите в лс", "пишите в личку",
    "в личку", "в лс", "напишите", "жду ответа", "уже сдали", "уже продали",
    "уже сдана", "уже продана", "спасибо", "ок", "окей", "договорились"
]

def is_low_signal(raw_text: str) -> bool:
    stripped = raw_text.strip().lower().strip("?!.,🔥❤️👍😊 \n\t")
    if not stripped or stripped in LOW_SIGNAL_PHRASES:
        return True
    if len(stripped.split()) < MIN_TOTAL_WORDS:
        return True
    return False

def is_piano_lesson_request(text_lower: str) -> bool:
    has_instrument = any(re.search(w, text_lower) for w in MUSIC_INSTRUMENT_WORDS)
    has_intent = any(stem in text_lower for stem in MUSIC_INTENT_STEMS)
    return has_instrument and has_intent

MAX_FINGERPRINTS = 1000
_seen_fingerprints = OrderedDict()

def _content_fingerprint(raw_text: str) -> str:
    normalized = re.sub(r'[^\w\s]', '', raw_text.strip().lower())
    normalized = re.sub(r'\s+', ' ', normalized)
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()

# Порог схожести для "почти дубля" — когда человек чуть подправил текст и
# отправил заново (например, дописал "в месяц" для ясности). Обычная
# дедупликация по хешу такое не ловит, потому что текст формально другой.
FUZZY_DUPLICATE_THRESHOLD = 0.85

def _is_near_duplicate(new_text, existing_records):
    """Проверяет, есть ли среди уже сохранённых записей текст, почти
    идентичный новому — не побуквенно (это делает _content_fingerprint), а
    по общей похожести. Ловит случаи вроде повторной отправки той же заявки
    с небольшой правкой формулировки в течение короткого времени.
    Важно: одной только текстовой схожести недостаточно — короткие
    объявления часто похожи по ШАБЛОНУ фразы ("Ищу квартиру X в Y до Z евро"),
    даже когда X/Y/Z (то есть сама суть) совершенно разные. Поэтому
    дополнительно требуем совпадения набора чисел в тексте (цена, комнаты,
    даты) — единственных деталей, которые реально отличают одно объявление
    от другого при похожем шаблоне."""
    new_norm = re.sub(r'\s+', ' ', new_text.strip().lower())
    new_numbers = set(re.findall(r'\d+', new_norm))
    for r in existing_records:
        existing_norm = re.sub(r'\s+', ' ', r.get('text', '').strip().lower())
        if abs(len(new_norm) - len(existing_norm)) > max(len(new_norm), len(existing_norm)) * 0.3:
            continue  # длины слишком разные — не тратим время на детальное сравнение
        existing_numbers = set(re.findall(r'\d+', existing_norm))
        if new_numbers != existing_numbers:
            continue  # разные числа (цена/комнаты/даты) — разные объявления
        if SequenceMatcher(None, new_norm, existing_norm).ratio() >= FUZZY_DUPLICATE_THRESHOLD:
            return True
    return False

def is_duplicate_content(raw_text: str) -> bool:
    """Проверка на дубликат по контенту"""
    fp = _content_fingerprint(raw_text)
    if fp in _seen_fingerprints:
        return True
    _seen_fingerprints[fp] = True
    if len(_seen_fingerprints) > MAX_FINGERPRINTS:
        _seen_fingerprints.popitem(last=False)
    return False

SEMANTIC_DEDUP_WINDOW_SECONDS = 60 * 60  # 1 час вместо 20 минут
MAX_SEMANTIC_KEYS = 1000
_seen_semantic = OrderedDict()

def is_semantic_duplicate(category, locations, start_d, end_d, price_range, rooms, price_type) -> bool:
    """Проверка на семантический дубликат"""
    loc_key = "|".join(sorted([l.lower() for l in locations]) if isinstance(locations, list) else [str(locations).lower()])
    key = f"{category}|{loc_key}|{start_d}|{end_d}|{price_range}|{rooms}|{price_type}"
    now = datetime.now()
    last_seen = _seen_semantic.get(key)
    if last_seen and (now - last_seen).total_seconds() < SEMANTIC_DEDUP_WINDOW_SECONDS:
        return True
    _seen_semantic[key] = now
    if len(_seen_semantic) > MAX_SEMANTIC_KEYS:
        _seen_semantic.popitem(last=False)
    return False

logging.basicConfig(format='[%(levelname) 5s/%(asctime)s] %(name)s: %(message)s', level=logging.WARNING)

# ==========================================
# ЗАЩИТА ОТ ЗАПУСКА НЕСКОЛЬКИХ КОПИЙ ОДНОВРЕМЕННО
# ==========================================
LOCK_FILE = "parser.lock"
LOCK_STALE_SECONDS = 90  # если файл-замок старше — считаем, что процесс мёртв

def acquire_single_instance_lock():
    now = datetime.now().timestamp()
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, "r") as f:
                last_heartbeat = float(f.read().strip())
        except Exception:
            last_heartbeat = 0
        if now - last_heartbeat < LOCK_STALE_SECONDS:
            print("❌ Похоже, уже запущена другая копия parser_telethon.py — это и есть причина дублей.")
            print(f"   Закрой все остальные окна со скриптом, либо, если уверен что их нет, удали файл {LOCK_FILE} и запусти снова.")
            sys.exit(1)
    with open(LOCK_FILE, "w") as f:
        f.write(str(now))

def release_lock():
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    except Exception:
        pass

async def heartbeat_loop():
    while True:
        try:
            with open(LOCK_FILE, "w") as f:
                f.write(str(datetime.now().timestamp()))
        except Exception:
            pass
        await asyncio.sleep(30)

async def expiry_cleanup_loop():
    """Раз в несколько часов удаляет из базы заявки с прошедшими датами —
    скрипт может работать сутками, и заявка, актуальная при старте, может
    устареть прямо во время работы."""
    while True:
        await asyncio.sleep(6 * 60 * 60)
        try:
            expired = cleanup_expired_records()
            if expired:
                print(f"🧹 Удалено просроченных заявок из базы: {len(expired)}")
        except Exception as e:
            print(f"⚠️ Ошибка при очистке просроченных заявок: {e}")

async def self_healing_loop():
    """Раз в несколько часов пересчитывает комнаты/цену/даты/категорию у
    ВСЕХ записей в памяти, не только при перезапуске. Раньше пересчёт
    (load_full_records) срабатывал только один раз, при старте — если
    скрипт работает непрерывно много дней (а он работает), однажды
    сохранённая с ошибкой запись так и оставалась неверной все эти дни,
    хотя сам баг в коде мог быть давно исправлен."""
    while True:
        await asyncio.sleep(6 * 60 * 60)
        try:
            healed = 0
            moved = 0
            removed = 0
            lists_by_type = {
                'rent_demand': db.rent_demands, 'rent_supply': db.rent_supplies,
                'sale_demand': db.sale_demands, 'sale_supply': db.sale_supplies,
            }
            for record_type, lst in list(lists_by_type.items()):
                for record in list(lst):
                    new_type = _refresh_record_fields(record, record_type)
                    healed += 1
                    if new_type is None:
                        # Текст больше не подходит ни под одну категорию —
                        # удаляем запись целиком, а не оставляем висеть в
                        # старой (возможно неверной) категории навсегда
                        db.remove_by_msg_key(record['msg_key'])
                        removed += 1
                        continue
                    if new_type != record_type and new_type in lists_by_type:
                        lst.remove(record)
                        lists_by_type[new_type].append(record)
                        moved += 1
                    persist_full_record(new_type, record)
            if moved or removed:
                print(f"🔄 Периодическое самолечение: пересчитано {healed} записей, "
                      f"переклассифицировано {moved}, удалено как более не подходящие {removed}")
        except Exception as e:
            print(f"⚠️ Ошибка периодического самолечения: {e}")

acquire_single_instance_lock()
atexit.register(release_lock)

# ==========================================
# ВКОНТАКТЕ — ДОПОЛНИТЕЛЬНЫЙ ИСТОЧНИК (посты и комментарии открытых групп)
# ==========================================
_vk_session = None

def vk_get_session():
    """Ленивая инициализация VK API — только если задан токен и установлена
    библиотека vk_api. Если что-то не настроено, весь блок ВК просто не
    активируется, остальной парсер работает как обычно."""
    global _vk_session
    if _vk_session is not None:
        return _vk_session
    if not VK_AVAILABLE or not VK_ACCESS_TOKEN:
        return None
    try:
        session = vk_api.VkApi(token=VK_ACCESS_TOKEN)
        _vk_session = session.get_api()
    except Exception as e:
        # Без этой защиты ошибка тут (например, некорректный токен) тихо
        # убивала бы всю фоновую задачу опроса ВК — ни одной строки в
        # консоли, а весь остальной бот при этом продолжал бы работать как
        # ни в чём не бывало, что выглядело бы как "ВК просто не работает"
        print(f"⚠️ ВК: не удалось создать сессию (проверь VK_ACCESS_TOKEN): {e}")
        return None
    return _vk_session

def vk_extract_identifier(raw):
    """Достаёт идентификатор группы из ссылки или короткого ввода — можно
    указывать просто число, "clubXXXX", короткое имя группы, или целую
    ссылку вида https://vk.ru/... / https://vk.com/..."""
    raw = raw.strip()
    raw = re.sub(r'^https?://(www\.)?vk\.(ru|com)/', '', raw)
    raw = raw.rstrip('/')
    if raw.startswith('club'):
        raw = raw[len('club'):]
    elif raw.startswith('public'):
        raw = raw[len('public'):]
    return raw

def vk_resolve_group_ids(api, raw_ids):
    """Приводит любой формат (число, clubXXXX, короткое имя, ссылка) к
    чистому числовому ID группы — короткие имена резолвятся через API
    (groups.getById принимает и числа, и screen_name одинаково)."""
    resolved = []
    for raw in raw_ids:
        ident = vk_extract_identifier(raw)
        if ident.isdigit():
            resolved.append(ident)
            continue
        try:
            info = api.groups.getById(group_id=ident)
            group_info = info[0] if isinstance(info, list) else info.get("groups", [{}])[0]
            gid = str(group_info["id"])
            resolved.append(gid)
            print(f"🌐 ВК: «{raw}» -> ID {gid} ({group_info.get('name', '')})")
        except Exception as e:
            print(f"⚠️ ВК: не удалось определить ID группы для «{raw}»: {e}")
    return resolved

def vk_get_checkpoint(group_id):
    row = dedup_conn.execute(
        "SELECT last_post_ts, last_comment_ts FROM vk_checkpoints WHERE group_id = ?", (group_id,)
    ).fetchone()
    if row:
        return row[0], row[1]
    return 0, 0

def vk_save_checkpoint(group_id, last_post_ts, last_comment_ts):
    dedup_conn.execute(
        "INSERT INTO vk_checkpoints (group_id, last_post_ts, last_comment_ts) VALUES (?, ?, ?) "
        "ON CONFLICT(group_id) DO UPDATE SET last_post_ts=excluded.last_post_ts, last_comment_ts=excluded.last_comment_ts",
        (group_id, last_post_ts, last_comment_ts)
    )
    dedup_conn.commit()

async def process_external_text(text, source_url, source_title, author_name, author_url, item_key):
    """Общий конвейер обработки текста из внешнего источника (сейчас — ВК,
    но написано без привязки к конкретной площадке) через ту же
    классификацию, базу и отправку алертов, что и для Telegram."""
    if not text or len(text.split()) < 3:
        return

    raw_text = text
    text_lower = raw_text.lower()

    r_type = classify_transaction_type(raw_text)
    if r_type is None:
        return

    my_locations = detect_locations(raw_text)
    if not my_locations:
        my_locations = detect_locations(source_title)

    u_rooms = extract_rooms(raw_text) or "не указана"
    u_rooms_all = extract_all_rooms(raw_text)
    chat_title = source_title
    clean_text = html.escape(raw_text)[:1500]
    sender_name = author_name or "ВКонтакте"

    if r_type in ('rent_demand', 'rent_supply'):
        u_price, u_price_type, u_price_dict, u_currency = extract_price_with_type_full(raw_text)
        u_all_prices = extract_all_period_prices(raw_text)
        u_price_display = f"{u_price}{currency_symbol(u_currency)} ({u_price_type})" if u_price else "не указана"
        start_d, end_d = dp.parse_relative_dates(text_lower)

        if r_type == 'rent_demand':
            is_new = db.add_rent_demand(item_key, 0, chat_title, raw_text, sender_name, "vk",
                                        source_url, my_locations, start_d, end_d)
            if is_new:
                alert = (
                    f"🙋‍♂️ <b>[VK] КЛИЕНТ ИЩЕТ АРЕНДУ</b>\n────────────────\n"
                    f"📍 Локация: {locations_display(my_locations)}\n💰 Бюджет: {u_price_display} | 📦 Комнат: {u_rooms}\n"
                    f"🗂 Источник: {chat_title}\n────────────────\n\n{clean_text}"
                )
                await send_via_bot(RENT_CHAT_ID, alert, source_url, author_url, locations=my_locations)
                avg_price = get_average_price(u_price_dict) if u_price_dict else u_price
                await handle_matches('demand', my_locations, u_rooms, avg_price, price_type=u_price_type,
                                     price_dict=u_price_dict, start_date=start_d, clean_text=clean_text,
                                     message_link=source_url, user_link=author_url, chat_title=chat_title,
                                     transaction_type="АРЕНДА", currency=u_currency, end_date=end_d,
                                     rooms_all=u_rooms_all)
        else:
            is_new = db.add_rent_supply(item_key, 0, chat_title, raw_text, sender_name, "vk",
                                        source_url, my_locations, start_d, end_d)
            if is_new:
                alert = (
                    f"🏠 <b>[VK] ХОЗЯИН СДАЕТ НЕДВИЖИМОСТЬ</b>\n────────────────\n"
                    f"📍 Локация: {locations_display(my_locations)}\n📆 Доступно с: {start_d if start_d else 'не указано'}\n"
                    f"💰 Цена: {u_price_display} | 📦 Комнат: {u_rooms}\n"
                    f"🗂 Источник: {chat_title}\n────────────────\n\n{clean_text}"
                )
                await send_via_bot(RENT_CHAT_ID, alert, source_url, author_url, locations=my_locations)
                avg_price = get_average_price(u_price_dict) if u_price_dict else u_price
                await handle_matches('supply', my_locations, u_rooms, avg_price, price_type=u_price_type,
                                     price_dict=u_price_dict, start_date=start_d, clean_text=clean_text,
                                     message_link=source_url, user_link=author_url, chat_title=chat_title,
                                     transaction_type="АРЕНДА", currency=u_currency, end_date=end_d,
                                     rooms_all=u_rooms_all)
    else:
        u_price, u_currency = extract_price_and_currency(raw_text)
        u_sale_price_display = f"{u_price}{currency_symbol(u_currency)}" if u_price else "не указана"

        if r_type == 'sale_demand':
            is_new = db.add_sale_demand(item_key, 0, chat_title, raw_text, sender_name, "vk",
                                        source_url, my_locations, u_rooms, u_price)
            if is_new:
                alert = (
                    f"🧐 <b>[VK] ПОИСК НА ПОКУПКУ НЕДВИЖИМОСТИ</b>\n────────────────\n"
                    f"📍 Локация: {locations_display(my_locations)}\n💰 Бюджет: {u_sale_price_display} | 📦 Комнат: {u_rooms}\n"
                    f"🗂 Источник: {chat_title}\n────────────────\n\n{clean_text}"
                )
                await send_via_bot(MY_CHAT_ID, alert, source_url, author_url, locations=my_locations)
                await handle_matches('sale_demand', my_locations, u_rooms, u_price, price_type=None, price_dict=None,
                                     start_date=None, clean_text=clean_text, message_link=source_url,
                                     user_link=author_url, chat_title=chat_title, transaction_type="ПОКУПКА/ПРОДАЖА",
                                     currency=u_currency, rooms_all=u_rooms_all)
        else:
            is_new = db.add_sale_supply(item_key, 0, chat_title, raw_text, sender_name, "vk",
                                        source_url, my_locations, u_rooms, u_price)
            if is_new:
                alert = (
                    f"🏢 <b>[VK] ПРОДАЖА ОТ СОБСТВЕННИКА / АГЕНТА</b>\n────────────────\n"
                    f"📍 Локация: {locations_display(my_locations)}\n💰 Цена: {u_sale_price_display} | 📦 Комнат: {u_rooms}\n"
                    f"🗂 Источник: {chat_title}\n────────────────\n\n{clean_text}"
                )
                await send_via_bot(MY_CHAT_ID, alert, source_url, author_url, locations=my_locations)
                await handle_matches('sale_supply', my_locations, u_rooms, u_price, price_type=None, price_dict=None,
                                     start_date=None, clean_text=clean_text, message_link=source_url,
                                     user_link=author_url, chat_title=chat_title, transaction_type="ПОКУПКА/ПРОДАЖА",
                                     currency=u_currency, rooms_all=u_rooms_all)

def vk_wall_get(api, group_id, count=20):
    owner_id = f"-{group_id}" if not str(group_id).startswith("-") else group_id
    return api.wall.get(owner_id=owner_id, count=count, extended=0)

def vk_wall_get_comments(api, group_id, post_id, count=100):
    owner_id = f"-{group_id}" if not str(group_id).startswith("-") else group_id
    return api.wall.getComments(owner_id=owner_id, post_id=post_id, count=count, sort="desc", extended=0)

async def vk_poll_group(group_id):
    api = vk_get_session()
    if api is None:
        return

    last_post_ts, last_comment_ts = vk_get_checkpoint(group_id)
    new_last_post_ts = last_post_ts
    new_last_comment_ts = last_comment_ts

    try:
        wall = await asyncio.to_thread(vk_wall_get, api, group_id, 30)
    except Exception as e:
        print(f"⚠️ ВК: не удалось получить стену группы {group_id}: {e}")
        return

    posts = wall.get("items", [])
    group_title = f"ВК-группа {group_id}"

    for post in posts:
        post_id = post.get("id")
        post_ts = post.get("date", 0)
        text = post.get("text", "")
        owner_id_raw = post.get("owner_id", f"-{group_id}")
        post_url = f"https://vk.com/wall{owner_id_raw}_{post_id}"

        if post_ts > last_post_ts:
            item_key = f"vk_post_{group_id}_{post_id}"
            from_id = post.get("from_id")
            author_url = f"https://vk.com/id{from_id}" if from_id and from_id > 0 else None
            try:
                await process_external_text(text, post_url, group_title, None, author_url, item_key)
            except Exception as e:
                print(f"⚠️ ВК: ошибка обработки поста {item_key}: {e}")
            new_last_post_ts = max(new_last_post_ts, post_ts)

        # Комментарии проверяем только у относительно свежих постов (30 дней) —
        # у старых постов новые комментарии маловероятны, а опрашивать всю
        # историю на каждом цикле было бы избыточно и дорого по квоте API
        if post_ts < last_comment_ts - 30 * 24 * 60 * 60:
            continue
        try:
            comments_resp = await asyncio.to_thread(vk_wall_get_comments, api, group_id, post_id, 100)
        except Exception as e:
            print(f"⚠️ ВК: не удалось получить комментарии поста {post_id}: {e}")
            continue

        for comment in comments_resp.get("items", []):
            c_ts = comment.get("date", 0)
            if c_ts <= last_comment_ts:
                continue
            c_id = comment.get("id")
            c_text = comment.get("text", "")
            c_from_id = comment.get("from_id")
            c_author_url = f"https://vk.com/id{c_from_id}" if c_from_id and c_from_id > 0 else None
            c_url = f"{post_url}?reply={c_id}"
            item_key = f"vk_comment_{group_id}_{post_id}_{c_id}"
            try:
                await process_external_text(c_text, c_url, group_title, None, c_author_url, item_key)
            except Exception as e:
                print(f"⚠️ ВК: ошибка обработки комментария {item_key}: {e}")
            new_last_comment_ts = max(new_last_comment_ts, c_ts)

    vk_save_checkpoint(group_id, new_last_post_ts, new_last_comment_ts)

async def vk_poll_loop():
    """Периодически опрашивает стены и комментарии заданных групп ВК —
    в отличие от Telegram, ВК не умеет сам присылать события по чужим
    группам, поэтому только через опрос по расписанию."""
    if not VK_ACCESS_TOKEN or not VK_GROUP_IDS:
        return
    if not VK_AVAILABLE:
        print("⚠️ ВКонтакте настроен (задан токен), но библиотека vk_api не установлена — "
              "выполни: pip install vk_api")
        return

    try:
        api = vk_get_session()
        if api is None:
            print("⚠️ ВК: не удалось инициализировать сессию — проверь VK_ACCESS_TOKEN")
            return

        # Приводим любой формат из .env (число, clubXXXX, короткое имя, ссылка)
        # к чистым числовым ID один раз при старте
        resolved_group_ids = await asyncio.to_thread(vk_resolve_group_ids, api, VK_GROUP_IDS)
        if not resolved_group_ids:
            print("⚠️ ВК: ни одна группа не была успешно определена — опрос не запущен")
            return
    except Exception as e:
        # Без этой защиты ЛЮБАЯ неожиданная ошибка на старте (не только
        # сессия) тихо убивала бы всю задачу опроса ВК — без единой строки
        # в консоли, пока остальной бот продолжал бы работать как обычно
        print(f"⚠️ ВК: не удалось запустить опрос ({e}) — блок ВК отключён до перезапуска")
        return

    print(f"🌐 ВКонтакте подключено — отслеживается групп: {len(resolved_group_ids)}")
    while True:
        for group_id in resolved_group_ids:
            try:
                await vk_poll_group(group_id)
            except Exception as e:
                print(f"⚠️ ВК: ошибка опроса группы {group_id}: {e}")
        await asyncio.sleep(VK_POLL_INTERVAL_SECONDS)

# ==========================================
# ХРАНИЛИЩЕ ДЕДУПЛИКАЦИИ НА ДИСКЕ (переживает перезапуск скрипта)
# ==========================================
DEDUP_DB_PATH = "realty_leads.db"

def init_dedup_store():
    conn = sqlite3.connect(DEDUP_DB_PATH, check_same_thread=False)
    conn.execute("""CREATE TABLE IF NOT EXISTS sent_log (
        msg_key TEXT PRIMARY KEY,
        content_hash TEXT,
        ts TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sent_log_hash ON sent_log(content_hash)")
    # Раньше на диск сохранялся только "отпечаток" сообщения (для защиты от
    # повторной отправки алерта), а сами данные объекта (локация, цена, даты,
    # комнаты) жили только в оперативной памяти и полностью терялись при
    # каждом перезапуске скрипта — из-за этого вручную добавленные объекты
    # переставали участвовать в мэтчинге после рестарта, хотя формально
    # оставались "сохранены" (просто не давали добавить себя же повторно).
    conn.execute("""CREATE TABLE IF NOT EXISTS records (
        msg_key TEXT PRIMARY KEY,
        record_type TEXT NOT NULL,
        data_json TEXT NOT NULL,
        ts TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_records_type ON records(record_type)")
    # Для ВКонтакте нужно ещё знать, ДО КАКОГО МОМЕНТА мы уже проверили
    # стену группы и комментарии — иначе каждый цикл опроса пришлось бы
    # заново перебирать всю историю. sent_log/records переиспользуются
    # как есть (msg_key просто получает префикс "vk_")
    conn.execute("""CREATE TABLE IF NOT EXISTS vk_checkpoints (
        group_id TEXT PRIMARY KEY,
        last_post_ts INTEGER DEFAULT 0,
        last_comment_ts INTEGER DEFAULT 0
    )""")
    # Города/районы, которые пользователь скрыл через меню /settings —
    # присутствие строки здесь значит "не показывать алерты по этому месту"
    conn.execute("""CREATE TABLE IF NOT EXISTS disabled_locations (
        location TEXT PRIMARY KEY
    )""")
    # Общие настройки-переключатели (сейчас — только "показывать только
    # объявления с указанной ценой"), хранится как простая пара ключ-значение
    conn.execute("""CREATE TABLE IF NOT EXISTS bot_settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )""")
    # Чаты, в которые уже отправлена постоянная клавиатура с кнопкой
    # "⚙️ Настройки" — чтобы не слать её заново при каждом перезапуске
    conn.execute("""CREATE TABLE IF NOT EXISTS keyboard_shown_chats (
        chat_id INTEGER PRIMARY KEY
    )""")
    conn.commit()
    return conn

dedup_conn = init_dedup_store()

# ==========================================
# НАСТРОЙКИ (города/районы + фильтр по цене) — управляются через мини-апп
# ==========================================
DISABLED_LOCATIONS = set()

def _upstash_request(path, method="GET", body=None):
    """Синхронный запрос к Upstash REST API — вызывается только через
    asyncio.to_thread, чтобы не блокировать event loop (тот же подход,
    что и для синхронной библиотеки vk_api)."""
    import urllib.request
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{UPSTASH_REDIS_URL}/{path}",
        data=data,
        headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}", "Content-Type": "application/json"},
        method=method
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())

async def _fetch_disabled_from_upstash():
    """None — мини-апп не настроен или временно недоступен (тогда
    вызывающий код использует локальную копию как запасной вариант).
    Иначе — актуальный набор выключенных мест из общего хранилища."""
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return None
    try:
        result = await asyncio.to_thread(_upstash_request, "smembers/disabled_locations")
        return set(result.get("result", []))
    except Exception as e:
        print(f"⚠️ Мини-апп: не удалось получить настройки ({e}) — использую локальную копию")
        return None

async def _push_disabled_to_upstash():
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return
    try:
        names = list(DISABLED_LOCATIONS)
        pipeline = [["DEL", "disabled_locations"]]
        if names:
            pipeline.append(["SADD", "disabled_locations"] + names)
        await asyncio.to_thread(_upstash_request, "pipeline", "POST", pipeline)
    except Exception as e:
        print(f"⚠️ Мини-апп: не удалось отправить настройки ({e}) — изменение осталось только локально")

async def _load_disabled_locations():
    global DISABLED_LOCATIONS
    upstash_data = await _fetch_disabled_from_upstash()
    if upstash_data is not None:
        DISABLED_LOCATIONS = upstash_data
        # Копируем и в локальную базу — на случай, если в следующий раз
        # мини-апп будет временно недоступен при старте
        try:
            dedup_conn.execute("DELETE FROM disabled_locations")
            dedup_conn.executemany(
                "INSERT INTO disabled_locations (location) VALUES (?)",
                [(n,) for n in DISABLED_LOCATIONS]
            )
            dedup_conn.commit()
        except Exception:
            pass
        return
    try:
        rows = dedup_conn.execute("SELECT location FROM disabled_locations").fetchall()
        DISABLED_LOCATIONS = {r[0] for r in rows}
    except Exception as e:
        print(f"⚠️ Не удалось загрузить настройки локаций: {e}")

async def miniapp_sync_loop():
    """Периодически подтягивает изменения, сделанные через мини-апп (тот
    пишет напрямую в Upstash, минуя этот процесс) — без этого цикла
    изменения в веб-версии не подхватились бы, пока бот не перезапустят."""
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return
    global DISABLED_LOCATIONS, REQUIRE_PRICE, RENTAL_PERIOD_FILTER
    while True:
        await asyncio.sleep(MINIAPP_SYNC_INTERVAL_SECONDS)
        fresh = await _fetch_disabled_from_upstash()
        if fresh is not None and fresh != DISABLED_LOCATIONS:
            DISABLED_LOCATIONS = fresh
        fresh_price_setting = await _fetch_require_price_from_upstash()
        if fresh_price_setting is not None and fresh_price_setting != REQUIRE_PRICE:
            REQUIRE_PRICE = fresh_price_setting
        fresh_period_filter = await _fetch_rental_period_filter_from_upstash()
        if fresh_period_filter is not None and fresh_period_filter != RENTAL_PERIOD_FILTER:
            RENTAL_PERIOD_FILTER = fresh_period_filter
        fresh_price_ranges = await _fetch_price_range_settings_from_upstash()
        if fresh_price_ranges is not None and fresh_price_ranges != PRICE_RANGE_SETTINGS:
            PRICE_RANGE_SETTINGS.update(fresh_price_ranges)

def location_allowed(locations):
    """Разрешено ли отправлять алерт с такими локациями. Список локаций
    пустой (место не определено) — не фильтруем неизвестное, показываем.
    Иначе показываем, если хотя бы одна из локаций НЕ выключена
    пользователем через /settings."""
    if not locations:
        return True
    return any(loc not in DISABLED_LOCATIONS for loc in locations)

# "Показывать только объявления с указанной ценой" — простой переключатель
# да/нет, в отличие от локаций (там множество значений) тут только одно
# булево значение на весь бот
REQUIRE_PRICE = False

def _load_require_price_local():
    global REQUIRE_PRICE
    try:
        row = dedup_conn.execute("SELECT value FROM bot_settings WHERE key = 'require_price'").fetchone()
        REQUIRE_PRICE = row is not None and row[0] == '1'
    except Exception as e:
        print(f"⚠️ Не удалось загрузить настройку «только с ценой»: {e}")

async def _fetch_require_price_from_upstash():
    """None — мини-апп не настроен или временно недоступен, тогда
    вызывающий код использует локальную копию."""
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return None
    try:
        result = await asyncio.to_thread(_upstash_request, "get/require_price")
        val = result.get("result")
        return None if val is None else (val == '1')
    except Exception as e:
        print(f"⚠️ Мини-апп: не удалось получить настройку «только с ценой» ({e}) — использую локальную копию")
        return None

async def _push_require_price_to_upstash():
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return
    try:
        await asyncio.to_thread(_upstash_request, f"set/require_price/{1 if REQUIRE_PRICE else 0}")
    except Exception as e:
        print(f"⚠️ Мини-апп: не удалось отправить настройку «только с ценой» ({e})")

async def _load_require_price():
    global REQUIRE_PRICE
    upstash_val = await _fetch_require_price_from_upstash()
    if upstash_val is not None:
        REQUIRE_PRICE = upstash_val
        try:
            dedup_conn.execute(
                "INSERT INTO bot_settings (key, value) VALUES ('require_price', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                ('1' if REQUIRE_PRICE else '0',)
            )
            dedup_conn.commit()
        except Exception:
            pass
        return
    _load_require_price_local()

async def _toggle_require_price():
    global REQUIRE_PRICE
    REQUIRE_PRICE = not REQUIRE_PRICE
    try:
        dedup_conn.execute(
            "INSERT INTO bot_settings (key, value) VALUES ('require_price', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ('1' if REQUIRE_PRICE else '0',)
        )
        dedup_conn.commit()
    except Exception:
        pass
    await _push_require_price_to_upstash()

def price_allowed(*prices):
    """Если включён режим «только с ценой» — пропускаем алерт, только если
    ВСЕ переданные цены указаны (не None). Без аргументов всегда разрешено
    (нечего проверять)."""
    if not REQUIRE_PRICE:
        return True
    return all(p is not None for p in prices)

# Фильтр по типу аренды: "all" (все), "monthly" (только месячная),
# "daily" (только посуточная). Как и REQUIRE_PRICE, применяется только к
# мэтчам по АРЕНДЕ — обычный, немэтчевый чат аренды фильтр не трогает
RENTAL_PERIOD_FILTER = "all"

def _load_rental_period_filter_local():
    global RENTAL_PERIOD_FILTER
    try:
        row = dedup_conn.execute("SELECT value FROM bot_settings WHERE key = 'rental_period_filter'").fetchone()
        RENTAL_PERIOD_FILTER = row[0] if row is not None and row[0] in ("all", "monthly", "daily") else "all"
    except Exception as e:
        print(f"⚠️ Не удалось загрузить настройку «тип аренды»: {e}")

async def _fetch_rental_period_filter_from_upstash():
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return None
    try:
        result = await asyncio.to_thread(_upstash_request, "get/rental_period_filter")
        val = result.get("result")
        return val if val in ("all", "monthly", "daily") else None
    except Exception as e:
        print(f"⚠️ Мини-апп: не удалось получить настройку «тип аренды» ({e}) — использую локальную копию")
        return None

async def _push_rental_period_filter_to_upstash():
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return
    try:
        await asyncio.to_thread(_upstash_request, f"set/rental_period_filter/{RENTAL_PERIOD_FILTER}")
    except Exception as e:
        print(f"⚠️ Мини-апп: не удалось отправить настройку «тип аренды» ({e})")

async def _load_rental_period_filter():
    global RENTAL_PERIOD_FILTER
    upstash_val = await _fetch_rental_period_filter_from_upstash()
    if upstash_val is not None:
        RENTAL_PERIOD_FILTER = upstash_val
        try:
            dedup_conn.execute(
                "INSERT INTO bot_settings (key, value) VALUES ('rental_period_filter', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (RENTAL_PERIOD_FILTER,)
            )
            dedup_conn.commit()
        except Exception:
            pass
        return
    _load_rental_period_filter_local()

def period_allowed(price_type):
    """Фильтр по типу аренды. price_type, который не 'месячная' и не
    'посуточная' (например, "не указана", или это вообще не аренда, а
    продажа) — не фильтруем, всегда показываем: фильтр специально только
    про выбор между месячной и посуточной, а не про то, известен ли период."""
    if RENTAL_PERIOD_FILTER == "all":
        return True
    if price_type == "месячная":
        return RENTAL_PERIOD_FILTER == "monthly"
    if price_type == "посуточная":
        return RENTAL_PERIOD_FILTER == "daily"
    return True

# Границы цены — отдельно для месячной и посуточной аренды (например,
# "показывать только месячную аренду дороже 1000"). None означает "без
# ограничения". Все четыре значения — простые числа, поэтому хранятся и
# синхронизируются одним общим набором функций, а не четырьмя копиями
# кода, как для REQUIRE_PRICE/RENTAL_PERIOD_FILTER
PRICE_RANGE_KEYS = ("monthly_price_min", "monthly_price_max", "daily_price_min", "daily_price_max")
PRICE_RANGE_SETTINGS = {k: None for k in PRICE_RANGE_KEYS}

def _load_price_range_settings_local():
    for key in PRICE_RANGE_KEYS:
        try:
            row = dedup_conn.execute("SELECT value FROM bot_settings WHERE key = ?", (key,)).fetchone()
            PRICE_RANGE_SETTINGS[key] = int(row[0]) if row is not None and row[0] not in (None, '', 'none') else None
        except Exception as e:
            print(f"⚠️ Не удалось загрузить настройку «{key}»: {e}")

async def _fetch_price_range_settings_from_upstash():
    """None — мини-апп не настроен или временно недоступен, тогда
    вызывающий код использует локальную копию."""
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return None
    try:
        result = {}
        for key in PRICE_RANGE_KEYS:
            r = await asyncio.to_thread(_upstash_request, f"get/{key}")
            val = r.get("result")
            result[key] = int(val) if val not in (None, '', 'none') else None
        return result
    except Exception as e:
        print(f"⚠️ Мини-апп: не удалось получить диапазоны цен ({e}) — использую локальную копию")
        return None

async def _push_price_range_settings_to_upstash():
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return
    try:
        for key in PRICE_RANGE_KEYS:
            val = PRICE_RANGE_SETTINGS[key]
            await asyncio.to_thread(_upstash_request, f"set/{key}/{val if val is not None else 'none'}")
    except Exception as e:
        print(f"⚠️ Мини-апп: не удалось отправить диапазоны цен ({e})")

async def _load_price_range_settings():
    upstash_val = await _fetch_price_range_settings_from_upstash()
    if upstash_val is not None:
        PRICE_RANGE_SETTINGS.update(upstash_val)
        try:
            for key in PRICE_RANGE_KEYS:
                val = PRICE_RANGE_SETTINGS[key]
                dedup_conn.execute(
                    "INSERT INTO bot_settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, str(val) if val is not None else 'none')
                )
            dedup_conn.commit()
        except Exception:
            pass
        return
    _load_price_range_settings_local()

def price_range_allowed(price_type, *prices):
    """Фильтр по диапазону цены — отдельно для месячной и посуточной
    аренды (свои границы для каждой). Цены, которые не указаны (None), тут
    не проверяем — это отдельно покрывает REQUIRE_PRICE. Если для этого
    price_type обе границы не заданы — не фильтруем."""
    if price_type == "месячная":
        lo, hi = PRICE_RANGE_SETTINGS["monthly_price_min"], PRICE_RANGE_SETTINGS["monthly_price_max"]
    elif price_type == "посуточная":
        lo, hi = PRICE_RANGE_SETTINGS["daily_price_min"], PRICE_RANGE_SETTINGS["daily_price_max"]
    else:
        return True  # неприменимо — не аренда или период неизвестен
    if lo is None and hi is None:
        return True
    for p in prices:
        if p is None:
            continue
        if lo is not None and p < lo:
            return False
        if hi is not None and p > hi:
            return False
    return True

def _keyboard_already_shown(chat_id):
    try:
        row = dedup_conn.execute(
            "SELECT 1 FROM keyboard_shown_chats WHERE chat_id = ?", (chat_id,)
        ).fetchone()
        return row is not None
    except Exception:
        return False

async def _ensure_settings_keyboard(chat_id):
    """Отправляет постоянную клавиатуру с кнопкой "⚙️ Настройки" внизу
    экрана — один раз на чат, не при каждом перезапуске. В отличие от
    инлайн-кнопок (привязаны к одному сообщению), такая кнопка остаётся
    внизу экрана постоянно, под любым следующим сообщением в этом чате —
    не нужно ни помнить, ни печатать команду /settings."""
    if chat_id == 0 or _keyboard_already_shown(chat_id):
        return
    try:
        await bot.send_message(
            chat_id,
            "⚙️ Кнопка настройки городов теперь всегда внизу экрана — жми в любой момент.",
            buttons=[[Button.text("⚙️ Настройки", resize=True)]]
        )
        dedup_conn.execute("INSERT OR IGNORE INTO keyboard_shown_chats (chat_id) VALUES (?)", (chat_id,))
        dedup_conn.commit()
    except Exception as e:
        print(f"⚠️ Не удалось отправить кнопку настроек в чат {chat_id}: {e}")

def persist_dedup_record(msg_key, content_hash):
    try:
        dedup_conn.execute(
            "INSERT OR IGNORE INTO sent_log (msg_key, content_hash) VALUES (?, ?)",
            (msg_key, content_hash)
        )
        dedup_conn.commit()
    except Exception as e:
        print(f"⚠️ Не удалось сохранить дедуп-запись на диск: {e}")

def _json_default(obj):
    if hasattr(obj, "isoformat"):  # datetime.date / datetime.datetime
        return obj.isoformat()
    return str(obj)

def persist_full_record(record_type, record):
    """Сохранить ПОЛНЫЕ данные объекта на диск (не только отпечаток) —
    чтобы после перезапуска скрипта объект продолжал участвовать в мэтчинге,
    а не только блокировал повторное добавление самого себя."""
    try:
        data_json = json.dumps(record, default=_json_default, ensure_ascii=False)
        dedup_conn.execute(
            "INSERT OR REPLACE INTO records (msg_key, record_type, data_json) VALUES (?, ?, ?)",
            (record['msg_key'], record_type, data_json)
        )
        dedup_conn.commit()
    except Exception as e:
        print(f"⚠️ Не удалось сохранить объект на диск: {e}")

def _deserialize_record(data_json):
    record = json.loads(data_json)
    for key in ("start", "end"):
        if record.get(key):
            try:
                record[key] = datetime.fromisoformat(record[key]).date()
            except (ValueError, TypeError):
                pass
    return record

def _first_match_position(text_lower, patterns):
    """Позиция самого раннего совпадения среди списка паттернов, или None."""
    positions = [m.start() for p in patterns for m in [re.search(p, text_lower)] if m]
    return min(positions) if positions else None

def _resolve_sale_direction(text_lower, has_supply, has_demand):
    """Определяет продажа это или покупка, когда сработали ОБА признака
    сразу. Раньше покупка побеждала всегда безусловно — но если текст
    явно начинается с "Продажа..." с конкретными деталями объекта (этаж,
    блок, метраж), а слово-признак покупки затесалось где-то дальше
    (например, в шаблонной фразе в конце), результат получался
    противоположным тому, что на самом деле написано. Теперь побеждает то,
    что встретилось РАНЬШЕ по тексту — обычно это и есть основное
    намерение автора."""
    if has_supply and has_demand:
        supply_pos = _first_match_position(text_lower, SALE_SUPPLY_WORDS)
        demand_pos = _first_match_position(text_lower, SALE_DEMAND_WORDS)
        if supply_pos is not None and demand_pos is not None:
            return 'sale_supply' if supply_pos < demand_pos else 'sale_demand'
    return 'sale_demand' if has_demand else 'sale_supply'

def _resolve_rent_direction(text_lower, has_supply, has_demand):
    """То же самое, что _resolve_sale_direction, но для аренды. Раньше
    предложение побеждало почти безусловно при совпадении обоих признаков
    сразу — из-за этого фразы вроде "кто-нибудь знает где сдаётся
    квартира" (человек ИЩЕТ, но внутри вопроса есть слово "сдаётся")
    ошибочно уходили в предложение. Теперь, как и в продаже, побеждает то,
    что встретилось РАНЬШЕ по тексту."""
    if has_supply and has_demand:
        supply_pos = _first_match_position(text_lower, RENT_SUPPLY_WORDS)
        demand_pos = _first_match_position(text_lower, RENT_NEED_WORDS)
        if supply_pos is not None and demand_pos is not None:
            return 'rent_supply' if supply_pos < demand_pos else 'rent_demand'
    return 'rent_demand' if has_demand else 'rent_supply'

def classify_transaction_type(text):
    """Определяет тип объявления (аренда/продажа, спрос/предложение) по
    тексту — воспроизводит ту же логику, что и живой обработчик сообщений,
    но отдельно, чтобы её можно было применить повторно при пересчёте уже
    сохранённых записей. Без этого смена правил классификации (например,
    порога "дорого -> продажа") никогда не применяется задним числом —
    объект, один раз неверно сохранённый как аренда, остаётся там навсегда,
    даже когда сам баг классификации уже давно исправлен.
    ВАЖНО: логику здесь нужно вручную синхронизировать с веткой
    "КУПЛЯ-ПРОДАЖА"/"АРЕНДА" в основном обработчике при её изменении."""
    text_lower = text.lower()

    has_property = any(re.search(w, text_lower) for w in PROPERTY_WORDS)
    has_rent_need_near = _words_near_property(text_lower, RENT_NEED_WORDS)
    has_rent_supply_near = _words_near_property(text_lower, RENT_SUPPLY_WORDS)
    has_rent_supply_strong_near = _words_near_property(text_lower, RENT_SUPPLY_STRONG_WORDS)
    has_sale_supply_near = _words_near_property(text_lower, SALE_SUPPLY_WORDS)
    has_sale_demand_near = _words_near_property(text_lower, SALE_DEMAND_WORDS)

    if any(re.search(w, text_lower) for w in INVESTMENT_MARKETING_WORDS):
        has_rent_supply_near = False
        has_rent_supply_strong_near = False
        has_sale_supply_near = False

    if any(re.search(w, text_lower) for w in SERVICE_AD_WORDS):
        has_rent_supply_near = False
        has_rent_supply_strong_near = False

    price, price_type, price_dict, currency = extract_price_with_type_full(text)
    is_high_price = (price is not None and price >= 15000 and currency in ('EUR', 'USD'))

    if has_sale_supply_near or has_sale_demand_near or (has_property and is_high_price):
        return _resolve_sale_direction(text_lower, has_sale_supply_near, has_sale_demand_near)

    if has_rent_need_near or has_rent_supply_near:
        return _resolve_rent_direction(text_lower, has_rent_supply_near, has_rent_need_near)

    return None

def _refresh_record_fields(record, record_type):
    """Пересчитывает комнаты/цену/даты/категорию заново из сохранённого
    текста записи — не доверяя значению, посчитанному в момент сохранения
    или предыдущего пересчёта. Возвращает актуальный record_type (может
    отличаться от переданного, если пересчитанная классификация теперь
    другая). Мутирует record на месте.
    Общая функция для load_full_records (пересчёт при старте) и
    self_healing_loop (периодический пересчёт во время работы) — раньше
    пересчёт происходил только при перезапуске скрипта, и если бот работал
    непрерывно много дней, однажды сохранённая с ошибкой запись так и
    оставалась неверной всё это время."""
    text = record.get('text', '')
    if not text:
        return record_type

    fresh_rooms = extract_rooms(text)
    if fresh_rooms is not None:
        record['rooms'] = fresh_rooms
    fresh_rooms_all = extract_all_rooms(text)
    if fresh_rooms_all:
        record['rooms_all'] = fresh_rooms_all
    record['property_category'] = extract_property_category(text)

    if record_type in ('rent_demand', 'rent_supply'):
        fresh_price, fresh_price_type, fresh_price_dict, fresh_currency = extract_price_with_type_full(text)
        if fresh_price is not None:
            record['price'] = fresh_price
            record['price_type'] = fresh_price_type
            record['currency'] = fresh_currency
        if fresh_price_dict:
            record['price_dict'] = fresh_price_dict
        fresh_all_prices = extract_all_period_prices(text)
        if fresh_all_prices:
            record['all_prices'] = fresh_all_prices

        fresh_start, fresh_end = dp.parse_relative_dates(text.lower())
        record['start'] = fresh_start
        record['end'] = fresh_end
    else:
        fresh_price, fresh_currency = extract_price_and_currency(text)
        # Тут (в отличие от аренды) НЕ используем "fresh_price is not None"
        # как условие перезаписи — цена продажи должна иметь право
        # ИСЧЕЗНУТЬ при пересчёте (например, санитарный порог теперь
        # отсеивает ранее захваченную цену аренды внутри смешанного текста)
        record['price'] = fresh_price
        record['currency'] = fresh_currency

    fresh_type = classify_transaction_type(text)
    # Если текст теперь НЕ подходит ни под одну категорию вообще (например,
    # "ЭЛИТНАЯ АРЕНДА..." — "аренда" тут просто существительное, не входит
    # ни в один список слов-действий) — раньше самолечение просто ничего
    # не делало и оставляло запись висеть в её СТАРОЙ, возможно неверной
    # категории навсегда, даже после множества перезапусков. Теперь в этом
    # случае явно сигнализируем вызывающему коду, что запись нужно удалить
    if fresh_type is None:
        return None
    return fresh_type

def load_full_records(max_age_days=90):
    """Загрузить объекты, сохранённые в предыдущих запусках, обратно в
    память — иначе после каждого перезапуска база для мэтчинга была бы
    пустой, даже если вручную добавленные объекты формально "сохранены"
    на диске (отпечаток) и не давали добавить себя повторно."""
    loaded = {'rent_demand': 0, 'rent_supply': 0, 'sale_demand': 0, 'sale_supply': 0}
    try:
        rows = dedup_conn.execute(
            "SELECT msg_key, record_type, data_json, ts FROM records WHERE ts >= datetime('now', ?)",
            (f"-{max_age_days} days",)
        ).fetchall()
    except Exception as e:
        print(f"⚠️ Не удалось загрузить сохранённые объекты: {e}")
        return loaded

    for msg_key, record_type, data_json, ts in rows:
        try:
            record = _deserialize_record(data_json)
        except Exception:
            continue

        # Записи, сохранённые до появления поля 'added_at', берут дату
        # создания из момента сохранения в БД — иначе для них нельзя было бы
        # посчитать возраст (а значит, они никогда не устареют по возрасту)
        if not record.get('added_at') and ts:
            record['added_at'] = str(ts)[:10]

        # Пересчитываем комнаты/цену/даты/категорию заново из сохранённого
        # текста — логика распознавания менялась много раз, без пересчёта
        # старые записи так и оставались бы с результатом версии кода на
        # момент их сохранения
        record_type = _refresh_record_fields(record, record_type)

        if record_type is None:
            # Текст больше не подходит ни под одну категорию — не грузим
            # его в память и стираем с диска, а не оставляем висеть там,
            # где он просто продолжал бы молча пропускаться при каждой
            # следующей загрузке
            try:
                dedup_conn.execute("DELETE FROM records WHERE msg_key = ?", (msg_key,))
                dedup_conn.commit()
            except Exception:
                pass
            continue

        target = {
            'rent_demand': db.rent_demands, 'rent_supply': db.rent_supplies,
            'sale_demand': db.sale_demands, 'sale_supply': db.sale_supplies,
        }.get(record_type)
        if target is None:
            continue
        target.append(record)
        db.manual_msg_ids[msg_key] = record
        loaded[record_type] += 1

    return loaded

client = TelegramClient('parser_session', API_ID, API_HASH,
                         connection_retries=None, retry_delay=5, auto_reconnect=True,
                         catch_up=True)
bot = TelegramClient('bot_session', API_ID, API_HASH,
                      connection_retries=None, retry_delay=5, auto_reconnect=True,
                      catch_up=True)

@bot.on(events.NewMessage())
async def settings_command(event):
    # Открывается и по команде /settings, и по нажатию постоянной кнопки
    # "⚙️ Настройки" внизу экрана — обе ведут на мини-апп напрямую, а не
    # на старое текстовое меню (та проверка текста вручную, а не через
    # pattern= у декоратора — так надёжнее для эмодзи)
    raw = (event.raw_text or "").strip()
    if raw != "/settings" and raw != "⚙️ Настройки":
        return
    await event.respond(
        "🗺 Настройка городов и фильтров — в мини-аппе:",
        buttons=[Button.url("⚙️ Открыть настройки", MINIAPP_DEEPLINK)]
    )


# Если у СПРОСА не указана дата окончания, считаем заявку устаревшей, когда
# дата начала прошла больше чем на столько дней (клиент почти наверняка уже
# нашёл вариант). Для ПРЕДЛОЖЕНИЯ без даты окончания (долгосрочная/бессрочная
# аренда) прошедшее начало НЕ считается признаком устаревания — объект мог
# просто оставаться в аренде дальше.
DEMAND_EXPIRY_GRACE_DAYS = 7
# Если у заявки на аренду вообще нет никаких дат (ни начала, ни конца) —
# раньше такая заявка не устаревала никогда. Теперь считаем её устаревшей
# через столько дней после добавления.
NO_DATE_EXPIRY_DAYS = 30
# У продажи/покупки дат в принципе нет как понятия — ориентируемся только на
# возраст записи. Порог больше, чем для аренды: сделки по недвижимости
# обычно решаются дольше, чем поиск съёмного жилья.
SALE_EXPIRY_DAYS = 60

def _record_age_days(record):
    added_at = record.get('added_at')
    if not added_at:
        return None
    try:
        added_date = datetime.fromisoformat(added_at).date()
    except (ValueError, TypeError):
        return None
    return (datetime.now().date() - added_date).days

def _is_expired(record, is_demand):
    """Проверяет, устарела ли запись относительно сегодняшней даты."""
    today = datetime.now().date()
    start = record.get('start')
    end = record.get('end')
    if isinstance(start, datetime):
        start = start.date()
    if isinstance(end, datetime):
        end = end.date()

    if end is not None:
        return end < today
    if start is not None:
        if is_demand:
            return (today - start).days > DEMAND_EXPIRY_GRACE_DAYS
        return False

    # Дат вообще нет — раньше такая запись не устаревала никогда
    age = _record_age_days(record)
    return age is not None and age > NO_DATE_EXPIRY_DAYS

def _is_expired_sale(record):
    """Продажа/покупка — дат нет как понятия, ориентируемся на возраст записи."""
    age = _record_age_days(record)
    return age is not None and age > SALE_EXPIRY_DAYS

# ==========================================
# БАЗА ДАННЫХ С ПОДДЕРЖКОЙ ПРОДАЖ И УЛУЧШЕННОЙ ДЕДУПЛИКАЦИЕЙ
# ==========================================
class DummyDatabase:
    def __init__(self):
        self.rent_demands = []
        self.rent_supplies = []
        self.sale_demands = []
        self.sale_supplies = []
        self.processed_msgs = set()
        self.content_hashes = set()
        self.manual_msg_ids = {}

    def _add_to_processed(self, msg_key, text_hash):
        """Добавить сообщение в обработанные"""
        if msg_key in self.processed_msgs or text_hash in self.content_hashes:
            return False
        self.processed_msgs.add(msg_key)
        self.content_hashes.add(text_hash)
        persist_dedup_record(msg_key, text_hash)
        return True

    def add_sale_supply(self, msg_key, chat_id, chat_title, text, sender_name, username, link, locations, rooms, price):
        text_hash = _content_fingerprint(text)
        if not self._add_to_processed(msg_key, text_hash):
            return False
        if _is_near_duplicate(text, self.sale_supplies):
            return False
        
        u_price, currency = extract_price_and_currency(text)
        u_rooms = extract_rooms(text) or rooms
        u_rooms_all = extract_all_rooms(text)
        u_property_category = extract_property_category(text)
        if isinstance(locations, str):
            locations = [locations]
        
        record = {
            'msg_key': msg_key, 'locations': locations, 'rooms': u_rooms, 'rooms_all': u_rooms_all, 'price': u_price,
            'currency': currency, 'property_category': u_property_category, 'text': text, 'link': link,
            'user': username, 'chat_title': chat_title, 'added_at': datetime.now().date().isoformat()
        }
        self.sale_supplies.append(record)
        self.manual_msg_ids[msg_key] = record
        persist_full_record('sale_supply', record)
        return True

    def add_sale_demand(self, msg_key, chat_id, chat_title, text, sender_name, username, link, locations, rooms, max_price):
        text_hash = _content_fingerprint(text)
        if not self._add_to_processed(msg_key, text_hash):
            return False
        if _is_near_duplicate(text, self.sale_demands):
            return False
        
        u_price, currency = extract_price_and_currency(text)
        u_rooms = extract_rooms(text) or rooms
        u_rooms_all = extract_all_rooms(text)
        u_property_category = extract_property_category(text)
        if isinstance(locations, str):
            locations = [locations]
        
        record = {
            'msg_key': msg_key, 'locations': locations, 'rooms': u_rooms, 'rooms_all': u_rooms_all, 'price': u_price,
            'currency': currency, 'property_category': u_property_category, 'text': text, 'link': link,
            'user': username, 'chat_title': chat_title, 'added_at': datetime.now().date().isoformat()
        }
        self.sale_demands.append(record)
        self.manual_msg_ids[msg_key] = record
        persist_full_record('sale_demand', record)
        return True

    def add_rent_demand(self, msg_key, chat_id, chat_title, text, sender_name, username, link, locations, start, end):
        text_hash = _content_fingerprint(text)
        if not self._add_to_processed(msg_key, text_hash):
            return False
        if _is_near_duplicate(text, self.rent_demands):
            return False
        
        u_price, price_type, _, currency = extract_price_with_type_full(text)
        all_prices = extract_all_period_prices(text)
        u_rooms = extract_rooms(text)
        u_rooms_all = extract_all_rooms(text)
        u_property_category = extract_property_category(text)
        if isinstance(locations, str):
            locations = [locations]
        
        record = {
            'msg_key': msg_key, 'locations': locations, 'rooms': u_rooms, 'rooms_all': u_rooms_all, 'price': u_price,
            'price_type': price_type, 'currency': currency, 'all_prices': all_prices, 'start': start, 'end': end,
            'property_category': u_property_category, 'text': text, 'link': link, 'user': username,
            'chat_title': chat_title, 'added_at': datetime.now().date().isoformat()
        }
        self.rent_demands.append(record)
        self.manual_msg_ids[msg_key] = record
        persist_full_record('rent_demand', record)
        return True

    def add_rent_supply(self, msg_key, chat_id, chat_title, text, sender_name, username, link, locations, start, end):
        text_hash = _content_fingerprint(text)
        if not self._add_to_processed(msg_key, text_hash):
            return False
        if _is_near_duplicate(text, self.rent_supplies):
            return False
        
        u_price, price_type, price_dict, currency = extract_price_with_type_full(text)
        all_prices = extract_all_period_prices(text)
        u_rooms = extract_rooms(text)
        u_rooms_all = extract_all_rooms(text)
        u_property_category = extract_property_category(text)
        if isinstance(locations, str):
            locations = [locations]
        
        record = {
            'msg_key': msg_key, 'locations': locations, 'rooms': u_rooms, 'rooms_all': u_rooms_all, 'price': u_price,
            'price_type': price_type, 'price_dict': price_dict, 'currency': currency, 'all_prices': all_prices,
            'start': start, 'end': end, 'property_category': u_property_category, 'text': text, 'link': link,
            'user': username, 'chat_title': chat_title, 'added_at': datetime.now().date().isoformat()
        }
        self.rent_supplies.append(record)
        self.manual_msg_ids[msg_key] = record
        persist_full_record('rent_supply', record)
        return True

    def remove_by_msg_key(self, msg_key):
        """Удалить объект по msg_key"""
        record = self.manual_msg_ids.get(msg_key)
        text_hash = _content_fingerprint(record['text']) if record else None

        self.rent_demands = [r for r in self.rent_demands if r['msg_key'] != msg_key]
        self.rent_supplies = [r for r in self.rent_supplies if r['msg_key'] != msg_key]
        self.sale_demands = [r for r in self.sale_demands if r['msg_key'] != msg_key]
        self.sale_supplies = [r for r in self.sale_supplies if r['msg_key'] != msg_key]
        if msg_key in self.manual_msg_ids:
            del self.manual_msg_ids[msg_key]
        self.processed_msgs.discard(msg_key)

        # Раньше отпечаток ТЕКСТА не снимался при удалении — только msg_key.
        # Из-за этого повторный ввод того же (или почти того же) текста после
        # удаления навсегда блокировался как "дубликат", хотя самого объекта
        # в базе уже не было. Снимаем отпечаток, только если он не используется
        # ни одной ещё оставшейся записью (на случай совпадения хэшей у двух
        # разных объектов)
        if text_hash is not None:
            still_used = any(
                _content_fingerprint(r['text']) == text_hash
                for lst in (self.rent_demands, self.rent_supplies, self.sale_demands, self.sale_supplies)
                for r in lst
            )
            if not still_used:
                self.content_hashes.discard(text_hash)

        try:
            dedup_conn.execute("DELETE FROM sent_log WHERE msg_key = ?", (msg_key,))
            if text_hash is not None:
                dedup_conn.execute("DELETE FROM sent_log WHERE content_hash = ?", (text_hash,))
            dedup_conn.execute("DELETE FROM records WHERE msg_key = ?", (msg_key,))
            dedup_conn.commit()
        except Exception as e:
            print(f"⚠️ Не удалось удалить запись с диска: {e}")

    def get_matching_supplies(self, demand_locations, rooms, max_price, demand_start, demand_end, price_type, rooms_all=None, property_category=None):
        matches = []
        d_start = demand_start.date() if isinstance(demand_start, datetime) else demand_start
        d_end = demand_end.date() if isinstance(demand_end, datetime) else demand_end
        my_rooms_all = rooms_all if rooms_all else ([rooms] if rooms else None)
        
        for s in self.rent_supplies:
            if _is_expired(s, is_demand=False):
                continue
            
            s_all_prices = s.get('all_prices') or {}
            if s.get('price_type') != price_type and price_type not in s_all_prices:
                continue
            
            loc_match = location_overlap(demand_locations, s['locations'])
            if not loc_match:
                continue
            
            # Клиент, явно попросивший виллу/таунхаус/коттедж, не должен
            # получать в подборке обычную квартиру в комплексе, даже если
            # число комнат совпадает — это разные типы недвижимости
            if not property_category_compatible(property_category, s.get('property_category')):
                continue
            
            s_start = s['start'].date() if isinstance(s['start'], datetime) else s['start']
            s_end = s['end'].date() if isinstance(s['end'], datetime) else s['end']
            
            # Сравниваем НАБОРЫ приемлемых комнат, а не единственное значение —
            # если клиент писал "1+1 или 1+0", а объект — "1+1", это совпадение
            s_rooms_all = s.get('rooms_all') or ([s['rooms']] if s.get('rooms') else None)
            if not _rooms_overlap(my_rooms_all, s_rooms_all):
                continue
            
            # Если у объекта есть цена именно за нужный клиенту период
            # (например, объект указал и месячную, и суточную цену) —
            # сравниваем с ней, а не с "основной" извлечённой ценой,
            # которая может относиться к другому периоду
            s_price_for_period = s_all_prices[price_type][0] if price_type in s_all_prices else s['price']
            
            if max_price is not None and s_price_for_period is not None:
                if s_price_for_period > max_price * 1.2:
                    continue
            
            # Объект должен успеть освободиться к моменту, когда нужно клиенту
            if s_start is not None and d_start is not None and s_start > d_start:
                continue
            
            # Если известны обе даты окончания — объект должен оставаться
            # доступным как минимум до конца срока, нужного клиенту.
            # Без этой проверки объект, свободный всего на пару недель,
            # мэтчился с клиентом, которому нужно на несколько месяцев
            if s_end is not None and d_end is not None and s_end < d_end:
                continue
            
            matches.append(s)
        
        return matches

    def get_matching_demands(self, supply_locations, rooms, supply_price, supply_start, supply_end, price_type, rooms_all=None, property_category=None):
        matches = []
        s_start = supply_start.date() if isinstance(supply_start, datetime) else supply_start
        s_end = supply_end.date() if isinstance(supply_end, datetime) else supply_end
        my_rooms_all = rooms_all if rooms_all else ([rooms] if rooms else None)
        
        for d in self.rent_demands:
            if _is_expired(d, is_demand=True):
                continue
            
            if d.get('price_type') != price_type:
                continue
            
            loc_match = location_overlap(supply_locations, d['locations'])
            if not loc_match:
                continue
            
            # Симметрично get_matching_supplies: если у ЭТОГО кандидата-
            # спроса явно указана вилла/таунхаус/коттедж, а у объекта,
            # который сейчас предлагают — нет, это не совпадение
            if not property_category_compatible(d.get('property_category'), property_category):
                continue
            
            d_start = d['start'].date() if isinstance(d['start'], datetime) else d['start']
            d_end = d['end'].date() if isinstance(d['end'], datetime) else d['end']
            
            d_rooms_all = d.get('rooms_all') or ([d['rooms']] if d.get('rooms') else None)
            if not _rooms_overlap(my_rooms_all, d_rooms_all):
                continue
            
            if supply_price is not None and d['price'] is not None:
                if supply_price > d['price'] * 1.2:
                    continue
            
            if s_start is not None and d_start is not None and s_start > d_start:
                continue
            
            if s_end is not None and d_end is not None and s_end < d_end:
                continue
            
            matches.append(d)
        
        return matches

    def get_matching_sale_supplies(self, demand_locations, rooms, max_price, rooms_all=None, property_category=None):
        matches = []
        my_rooms_all = rooms_all if rooms_all else ([rooms] if rooms else None)
        for s in self.sale_supplies:
            loc_match = location_overlap(demand_locations, s['locations'])
            if not loc_match:
                continue
            
            s_rooms_all = s.get('rooms_all') or ([s['rooms']] if s.get('rooms') else None)
            if not _rooms_overlap(my_rooms_all, s_rooms_all):
                continue
            
            if not property_category_compatible(property_category, s.get('property_category')):
                continue
            
            if max_price is not None and s['price'] is not None:
                if s['price'] > max_price * 1.2:
                    continue
            
            matches.append(s)
        
        return matches

    def get_matching_sale_demands(self, supply_locations, rooms, supply_price, rooms_all=None, property_category=None):
        matches = []
        my_rooms_all = rooms_all if rooms_all else ([rooms] if rooms else None)
        for d in self.sale_demands:
            loc_match = location_overlap(supply_locations, d['locations'])
            if not loc_match:
                continue
            
            d_rooms_all = d.get('rooms_all') or ([d['rooms']] if d.get('rooms') else None)
            if not _rooms_overlap(my_rooms_all, d_rooms_all):
                continue
            
            if not property_category_compatible(d.get('property_category'), property_category):
                continue
            
            if supply_price is not None and d['price'] is not None:
                if supply_price > d['price'] * 1.2:
                    continue
            
            matches.append(d)
        
        return matches

db = DummyDatabase()

def cleanup_expired_records():
    """Удалить из базы устаревшие заявки: у аренды — по дате (или по
    возрасту, если дат нет вообще), у продажи/покупки — только по возрасту,
    так как дат там в принципе нет. Раньше и то и другое могло оставаться
    в базе бессрочно и дальше мэтчиться с новыми объявлениями, хотя клиент
    почти наверняка уже нашёл вариант или объект больше не актуален."""
    expired = []
    for r in list(db.rent_demands):
        if _is_expired(r, is_demand=True):
            expired.append(('rent_demand', r['msg_key']))
    for r in list(db.rent_supplies):
        if _is_expired(r, is_demand=False):
            expired.append(('rent_supply', r['msg_key']))
    for r in list(db.sale_demands):
        if _is_expired_sale(r):
            expired.append(('sale_demand', r['msg_key']))
    for r in list(db.sale_supplies):
        if _is_expired_sale(r):
            expired.append(('sale_supply', r['msg_key']))

    for _, msg_key in expired:
        db.remove_by_msg_key(msg_key)

    return expired

# ==========================================
# ИНСТРУМЕНТЫ АВТО-ОПРЕДЕЛЕНИЯ
# ==========================================
def location_overlap(locations1, locations2):
    """Проверить, есть ли пересечение между двумя списками локаций"""
    if not locations1 or not locations2:
        return False
    
    locs1_lower = [l.lower() for l in (locations1 if isinstance(locations1, list) else [locations1])]
    locs2_lower = [l.lower() for l in (locations2 if isinstance(locations2, list) else [locations2])]
    
    for l1 in locs1_lower:
        for l2 in locs2_lower:
            if l1 == l2:
                return True
    
    # Фоллбэк "совпадение на уровне города" — только если хотя бы одна
    # сторона не называла конкретный район (искала/предлагала "по городу
    # в целом"). Если ОБЕ стороны назвали конкретные (разные) районы одного
    # города — это НЕ совпадение: "Авсаллар" и "Махмутлар" в Алании — разные
    # места, и мэтчить их только потому что оба в Алании, не нужно
    has_bare_city1 = any(l in CITY_NAMES_LOWER for l in locs1_lower)
    has_bare_city2 = any(l in CITY_NAMES_LOWER for l in locs2_lower)
    if not (has_bare_city1 or has_bare_city2):
        return False
    
    cities1 = set()
    cities2 = set()
    
    for l1 in locs1_lower:
        if l1 in DISTRICT_TO_CITY:
            cities1.add(DISTRICT_TO_CITY[l1])
        elif l1 in CITY_NAMES_LOWER:
            cities1.add(CITY_NAMES_LOWER[l1])
    
    for l2 in locs2_lower:
        if l2 in DISTRICT_TO_CITY:
            cities2.add(DISTRICT_TO_CITY[l2])
        elif l2 in CITY_NAMES_LOWER:
            cities2.add(CITY_NAMES_LOWER[l2])
    
    return len(cities1 & cities2) > 0

# Названия, для которых ПОДТВЕРЖДЁН риск попасть подстрокой внутрь более
# длинного слова (как "Ван" внутри "ванная") — только для них жертвуем
# падежными формами и требуем границу с обеих сторон. У остальных коротких
# названий (например "Оба") такого риска нет — их неоднозначность
# (совпадение с обычным словом "оба варианта") двусторонняя граница всё
# равно не решает (это точное совпадение строк, не совпадение подстроки
# внутри другого слова), а склонение ("в Обе") она бы сломала зря
_STRICT_BOUNDARY_NAMES = {"ван"}

def _location_search_pattern(name):
    """Слова на -а/-я и на мягкий знак (-ь) в русском склонении меняют
    последнюю букву (Анкара -> в Анкаре, Кестель -> в Кестеле), а не просто
    добавляют окончание, как "Стамбул -> Стамбуле". Поэтому для них ищем по
    основе без последней буквы (только левая граница)."""
    base = name.lower()
    if len(base) >= 5 and base[-1] in ("а", "я", "ь"):
        return re.escape(base[:-1])
    if base in _STRICT_BOUNDARY_NAMES:
        return re.escape(base) + r"\b"
    return re.escape(base)

def _is_cyrillic_word(s):
    return any("а" <= ch <= "я" or ch in "ёЁ" for ch in s.lower())

def _name_mentioned(text_lower, canonical_name):
    """Упоминание места — по русскому названию (с учётом падежей), по
    альтернативному русскому написанию (например "Аланья" вместо "Алания" —
    тоже с учётом падежей, "в Аланье"), ИЛИ по турецкому/английскому
    написанию латиницей (без падежей — иностранные слова в русском тексте
    обычно не склоняют, поэтому тут нужна граница с обеих сторон).
    Возвращает объект совпадения (с позицией в тексте) или None — позиция
    нужна, чтобы отличать реальные совпадения от коротких названий, которые
    на самом деле просто начало другого, более длинного места."""
    m = re.search(rf"\b{_location_search_pattern(canonical_name)}", text_lower)
    if m:
        return m
    for alias in LOCATION_ALIASES.get(canonical_name, ()):
        if _is_cyrillic_word(alias):
            pattern = rf"\b{_location_search_pattern(alias)}"
        else:
            pattern = rf"\b{re.escape(alias.lower())}\b"
        m = re.search(pattern, text_lower)
        if m:
            return m
    return None

def _levenshtein(a, b, max_dist):
    """Расстояние Левенштейна с ранним выходом, если оно уже превысило
    max_dist — не тратим время на заведомо слишком разные строки."""
    if abs(len(a) - len(b)) > max_dist:
        return max_dist + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
        if min(prev) > max_dist:
            return max_dist + 1
    return prev[-1]

def _fuzzy_max_distance(name_len):
    """Допустимое число опечаток растёт вместе с длиной названия — для
    коротких названий (типа "Оба", "Каш") даже одна опечатка слишком
    рискованна (велик шанс случайно попасть на постороннее слово той же
    длины), поэтому для них нечёткий поиск отключён — только точное
    совпадение и явно перечисленные варианты написания."""
    if name_len <= 5:
        return 0
    if name_len <= 8:
        return 1
    return 2

_fuzzy_location_index = None

def _build_fuzzy_location_index():
    """Собирает один раз (лениво, при первом обращении) плоский список
    (основа_для_сравнения, каноническое_имя) из всех городов, районов и
    ИХ АЛИАСОВ (турецкое/английское написание, альтернативные русские
    варианты) — используется только нечётким поиском, отдельно от
    основного точного механизма."""
    global _fuzzy_location_index
    if _fuzzy_location_index is not None:
        return _fuzzy_location_index
    index = []
    seen = set()

    def add(name):
        base = name.lower()
        if len(base) >= 5 and base[-1] in ("а", "я", "ь"):
            base = base[:-1]
        key = (base, name)
        if key not in seen:
            seen.add(key)
            index.append(key)

    for city, districts in LOCATIONS.items():
        add(city)
        for district in districts:
            add(district)
    for canonical, aliases in LOCATION_ALIASES.items():
        for alias in aliases:
            if _is_cyrillic_word(alias):
                add(alias)
            else:
                index.append((alias.lower(), canonical))

    _fuzzy_location_index = index
    return index

def _fuzzy_find_locations(text_lower):
    """Запасной вариант, когда точное совпадение (включая все алиасы и
    падежи) не нашло в сообщении ВООБЩЕ НИЧЕГО — ищет слова, отличающиеся
    от известного названия места на 1-2 опечатки. Не заменяет явные
    алиасы (те быстрее и надёжнее для уже известных вариантов написания),
    а ловит то, что заранее не предусмотрено."""
    words = re.findall(r'[а-яёa-z]{5,}', text_lower)
    if not words:
        return []
    index = _build_fuzzy_location_index()
    found = []
    for word in words:
        for base, canonical in index:
            max_dist = _fuzzy_max_distance(len(base))
            if max_dist == 0:
                continue
            if _levenshtein(word, base, max_dist) <= max_dist:
                if canonical not in found:
                    found.append(canonical)
                break
    return found

def detect_locations(text):
    """Извлечь все локации из текста — по возможности на уровне района, а не только города"""
    text_lower = text.lower()

    # Собираем ВСЕ совпадения с их позицией в тексте. Позиция нужна, чтобы
    # потом убрать случаи вроде "Конья" внутри "Коньяалты" — оба реальных,
    # разных турецких места из справочника, но короткое совпадает как
    # префикс более длинного и точного названия в той же позиции текста
    raw_hits = []  # (start, end, name)
    bare_city_positions = {}  # {город: (start, end)} — только для тех, что попали как ГОЛЫЙ город (без района)

    for city, districts in LOCATIONS.items():
        city_m = _name_mentioned(text_lower, city)
        district_found = False
        for district in districts:
            d_m = _name_mentioned(text_lower, district)
            if d_m:
                raw_hits.append((d_m.start(), d_m.end(), district))
                district_found = True
        # Город добавляем отдельной записью только если он назван,
        # а конкретный район в тексте не указан (иначе теряем точность)
        if city_m and not district_found:
            raw_hits.append((city_m.start(), city_m.end(), city))
            bare_city_positions[city] = (city_m.start(), city_m.end())

    # На каждой позиции начала совпадения оставляем только самое длинное —
    # это и есть самое точное (более длинное название не может быть
    # случайным совпадением префикса, в отличие от короткого)
    best_at_start = {}
    for start, end, name in raw_hits:
        length = end - start
        if start not in best_at_start or length > best_at_start[start][0]:
            best_at_start[start] = (length, name)

    found_locations = []
    for start in sorted(best_at_start):
        _, name = best_at_start[start]
        if name not in found_locations:
            found_locations.append(name)

    # "Алания ЦЕНТР" / "центр Алании" — это точнее, чем просто голый
    # город: город целиком (включая удалённые районы вроде Махмутлара)
    # не должен матчиться против конкретного запроса именно на центр.
    # Слово "центр" рядом с ГОЛЫМ городом (без района) заменяем на отдельную
    # псевдо-локацию "Город-Центр" — она больше не голый город, так что
    # общее правило "голый город подходит под любой район" на неё не
    # действует, и она совпадёт только с ТАКИМ ЖЕ явным упоминанием центра
    for city, (c_start, c_end) in bare_city_positions.items():
        if city not in found_locations:
            continue
        window_start = max(0, c_start - 20)
        window_end = min(len(text_lower), c_end + 20)
        window = text_lower[window_start:window_end]
        if re.search(r'центр', window):
            idx = found_locations.index(city)
            found_locations[idx] = f"{city}-Центр"

    # Точное совпадение (включая все алиасы и падежи) не нашло вообще
    # ничего — пробуем нечёткий поиск как запасной вариант, чтобы ловить
    # опечатки, которые заранее не были никак предусмотрены
    if not found_locations:
        found_locations = _fuzzy_find_locations(text_lower)

    # Раньше здесь был дефолт на "Алания", пока парсер работал только по ней.
    # Теперь, когда распознаются все города Турции, угадывать конкретный город
    # для сообщения без явной локации будет только портить мэтчинг между
    # разными городами — оставляем пустой список ("локация не указана")
    return found_locations

def locations_display(locations):
    """Строка локаций для вывода — с защитой от пустого списка"""
    if not locations:
        return "не указана"
    return ", ".join(locations)

def extract_all_rooms(text):
    """Найти ВСЕ упомянутые варианты комнат — если человек указал несколько
    приемлемых типов ("ищу 1+1 / 1+0 или студию"), раньше система запоминала
    только первый и матчила исключительно под него, хотя человек явно
    написал, что согласен и на другие варианты тоже."""
    text_lower = text.lower()
    rooms = []
    for m in re.finditer(r'\b(\d\s*\+\s*\d)\b', text):
        val = m.group(1).replace(" ", "")
        if val not in rooms:
            rooms.append(val)
    if (re.search(r'\b1\s*\+\s*0\b', text) or re.search(r'студи|studio', text_lower)) and "1+0" not in rooms:
        rooms.append("1+0")
    return rooms

def _rooms_overlap(rooms_a, rooms_b):
    """Совместимы ли два набора допустимых типов комнат. Если хотя бы одна
    сторона не указала конкретный тип — не фильтруем (как и раньше было
    поведение при rooms=None)."""
    if not rooms_a or not rooms_b:
        return True
    return bool(set(rooms_a) & set(rooms_b))

# Отдельно стоящие типы недвижимости (вилла/таунхаус/коттедж) — это не то же
# самое, что квартира в комплексе, даже при одинаковом числе комнат. Клиент,
# явно попросивший виллу, не должен получать в подборке обычную квартиру —
# такое несовпадение раньше вообще никак не проверялось, сравнивались
# только комнаты/цена/локация/даты, но не сам тип объекта
STANDALONE_PROPERTY_WORDS = [r"\bвилл", r"\bтаунхаус", r"\bкоттедж", r"\bкотедж", r"\bоттедж"]

def extract_property_category(text):
    """'standalone' — явно упомянута вилла/таунхаус/коттедж. None — тип не
    уточнён явно (обычная квартира/студия/дуплекс по умолчанию; None, а не
    отдельная категория "apartment", потому что большинство объявлений
    вообще не называют тип явно — не хотим случайно исключать их)."""
    text_lower = text.lower()
    if any(re.search(w, text_lower) for w in STANDALONE_PROPERTY_WORDS):
        return "standalone"
    return None

def property_category_compatible(demand_category, supply_category):
    """Несовпадение — только когда СПРОС конкретно просит виллу/дом/
    таунхаус, а у ПРЕДЛОЖЕНИЯ это явно не подтверждено (в том числе если
    тип вообще не уточнён — в этом рынке большинство объявлений без
    явного типа являются обычными квартирами, так что "не уточнено"
    считаем ЗА квартиру, а не как "могло быть что угодно"). Если спрос НЕ
    просил конкретно виллу — ограничений нет вообще, квартира тоже
    подходит."""
    if demand_category == "standalone" and supply_category != "standalone":
        return False
    return True

def extract_rooms(text):
    text_lower = text.lower()
    
    nm_match = re.search(r'\b(\d\s*\+\s*\d)\b', text)
    studio_match = re.search(r'\b1\s*\+\s*0\b', text) or re.search(r'студи|studio', text_lower)
    
    if nm_match and studio_match:
        # Если в тексте есть и "N+M", и упоминание студии — берём то, что
        # встретилось РАНЬШЕ по тексту. Раньше "N+M" побеждал всегда,
        # даже если это было второстепенное упоминание дальше по тексту
        # ("куплю студию, рассмотрю также 1+1") — из-за этого "студия"
        # как основное намерение терялась, и покупателя матчили не с тем
        if studio_match.start() < nm_match.start():
            return "1+0"
        return nm_match.group(1).replace(" ", "")
    
    if nm_match:
        return nm_match.group(1).replace(" ", "")
    if studio_match:
        return "1+0"
    return None

def extract_monthly_prices(text):
    """Извлечь цены за каждый месяц"""
    text_lower = text.lower()
    price_dict = {}
    
    months_ru = {
        "январ": 1, "февра": 2, "март": 3, "апрел": 4, "мае": 5, "мая": 5,
        "июн": 6, "июл": 7, "авгус": 8, "сентя": 9, "октя": 10, "нояб": 11, "дека": 12
    }
    
    pattern = r'(\w+)\s*[-–]\s*(\d+(?:[.,\s]\d{3})*)\s*(?:€|\$|евро|долл|lira|лир)'
    
    for match in re.finditer(pattern, text, re.IGNORECASE):
        month_word = match.group(1).lower()
        price_str = match.group(2)
        
        for m_key, m_num in months_ru.items():
            if m_key in month_word:
                try:
                    cleaned = re.sub(r'[^\d]', '', price_str)
                    price = int(cleaned)
                    price_dict[m_num] = price
                except ValueError:
                    pass
                break
    
    return price_dict if price_dict else None

CURRENCY_SYMBOLS = {'EUR': '€', 'USD': '$', 'TRY': '₺'}

def currency_symbol(currency):
    return CURRENCY_SYMBOLS.get(currency, '')

_PRICE_TOKEN_RE = r'(?<!\+)(\d+(?:[.,\s]\d{3})*)\s*(€|\$|евро|долл\w*|lira|лир\w*|тл\b|try\b|tl\b)'

def _classify_currency_token(token):
    t = token.lower()
    if t == '€' or t.startswith('евро'):
        return 'EUR'
    elif t == '$' or t.startswith('долл'):
        return 'USD'
    return 'TRY'

def _period_window(text_lower, matches, idx):
    """Окно текста для поиска периода (месяц/сутки) рядом с ценой matches[idx].
    Ограничено началом СЛЕДУЮЩЕЙ найденной цены — иначе широкое окно у первой
    цены может дотянуться до периода, который на самом деле относится ко второй
    ("2500 евро в месяц, или 200 евро в сутки" — без этого ограничения первая
    цена ошибочно подхватывала бы "в сутки" от второй)."""
    m = matches[idx]
    win_start = max(0, m.start() - 20)
    next_start = matches[idx + 1].start() if idx + 1 < len(matches) else len(text_lower)
    win_end = min(m.end() + 30, next_start)
    return text_lower[win_start:win_end]

# Вынесены в константы, чтобы использовать И в _detect_period (проверка
# внутри готового окна), И в _find_period_markers (поиск по всему тексту
# сразу, для случая с несколькими ценами — см. ниже)
#
# \d+\s*дн(я|ей|ь) — "на 15 дней"/"3 дня" и т.п.: срок БЕЗ предлога "в"/"за",
# как и с месяцами. Тут обязательно требуем ЧИСЛО перед "дн..." — голое
# "день" без числа слишком часто встречается не про срок аренды вообще
# ("на днях" = скоро, "добрый день", "день рождения"). А вот "сутки"/"суток"
# само по себе — уже достаточно однозначное слово, число перед ним не
# требуем (в отличие от "дней"): "50€ сутки" без предлога "в" — тоже
# показатель посуточной цены
_DAILY_PERIOD_RE = r'(посуточно|в сутки|\/сутки|за сутки|\bсутк\w*|в день|\/день|за день|daily|краткосроч|на короткий срок|\d+\s*дн(?:я|ей|ь)\b)'
# \bмес\b — сокращение "мес"/"мес." после ЛЮБОГО предлога, а не только
# перечисленных явно. Граница с обеих сторон — чтобы не зацепить
# "место"/"места". долг(ий|о|ая|ое|ие) — "долгий срок"/"долго"/"надолго" —
# именно с этими окончаниями, не голое "долг" (у него есть другое значение,
# задолженность). "под ВНЖ" — для вида на жительство нужен договор аренды
# не короче 6 месяцев. "до ноября"/"до сентября" — конечный месяц без числа
# обычно означает длительную аренду (короткую поездку описывают точными
# датами, а не целевым месяцем окончания)
_MONTHLY_PERIOD_RE = r'(monthly|ежемесячно|долгосро[кч]|длительн|надолго|месяц\w*|\bмес\b|долг(?:ий|о|ая|ое|ие)\b|\bвнж\b|до\s+(?:январ|феврал|март|апрел|мая|июн|июл|август|сентябр|октябр|ноябр|декабр))'

def _detect_period(window, price, currency):
    if re.search(_DAILY_PERIOD_RE, window):
        return "посуточная"
    if re.search(_MONTHLY_PERIOD_RE, window):
        return "месячная"
    return None

def _find_period_markers(text_lower):
    """Находит ВСЕ маркеры периода (посуточно/месячно) по всему тексту
    сразу, с их позициями — в отличие от _detect_period (которая просто
    проверяет "есть ли совпадение в готовом окне"), это нужно, чтобы потом
    раздать каждой цене БЛИЖАЙШИЙ маркер, не дав одному и тому же маркеру
    засчитаться сразу двум ценам (см. _closest_unclaimed_period)."""
    markers = []
    for m in re.finditer(_DAILY_PERIOD_RE, text_lower):
        markers.append((m.start(), m.end(), "посуточная"))
    for m in re.finditer(_MONTHLY_PERIOD_RE, text_lower):
        markers.append((m.start(), m.end(), "месячная"))
    return markers

def _closest_unclaimed_period(price_match, markers, claimed, max_distance=30, tight_distance=8):
    """Ближайший к данной цене маркер периода, который ещё не занят другой
    ценой. claimed — множество позиций начала уже использованных маркеров.

    Сначала ищем маркер СРАЗУ ПЕРЕД ценой (в пределах tight_distance) —
    это перевешивает чистое расстояние. Иначе "Краткосрочно 35€
    Долгосрочно 700€" даёт неверный результат: "долгосрочно" стоит ближе
    к "35€" по числу символов, чем "краткосрочно", хотя по смыслу метка
    перед ценой относится именно к НЕЙ, а не к следующей. Только если
    прямо перед ценой ничего нет, проверяем маркер сразу ПОСЛЕ неё, и
    только потом — более широкий поиск ближайшего в пределах max_distance
    (для формулировок с лишними словами между ценой и меткой)."""
    def dist_to(start, end):
        if end <= price_match.start():
            return price_match.start() - end
        if start >= price_match.end():
            return start - price_match.end()
        return 0

    before = [(s, e, p) for s, e, p in markers if s not in claimed and e <= price_match.start()]
    before = [x for x in before if dist_to(x[0], x[1]) <= tight_distance]
    if before:
        return min(before, key=lambda x: dist_to(x[0], x[1]))

    after = [(s, e, p) for s, e, p in markers if s not in claimed and s >= price_match.end()]
    after = [x for x in after if dist_to(x[0], x[1]) <= tight_distance]
    if after:
        return min(after, key=lambda x: dist_to(x[0], x[1]))

    remaining = [(s, e, p) for s, e, p in markers if s not in claimed and dist_to(s, e) <= max_distance]
    if remaining:
        return min(remaining, key=lambda x: dist_to(x[0], x[1]))
    return None

def extract_all_period_prices(text):
    """Найти ВСЕ цены с явно указанным периодом (месяц/сутки) в тексте.
    Раньше извлекалась только ПЕРВАЯ цена — если объявление содержит
    и месячную, и суточную цену ("2500 евро в месяц, или 200 евро в
    сутки"), суточная полностью терялась. Возвращает словарь вида
    {'месячная': (цена, валюта), 'посуточная': (цена, валюта)} —
    только периоды, где период назван явно рядом с ценой.

    Вместо фиксированного окна вокруг каждой цены (как в _detect_period)
    тут сначала находятся ВСЕ маркеры периода по всему тексту, а затем
    каждой цене достаётся ближайший к ней ЕЩЁ НЕ занятый маркер — иначе
    короткое слово-период между двумя ценами ("50€ сутки 1200€ месяц")
    могло засчитаться обеим сразу, и вторая цена терялась при записи в
    словарь по одинаковому ключу периода."""
    text_lower = text.lower()
    matches = list(re.finditer(_PRICE_TOKEN_RE, text, re.IGNORECASE))
    markers = _find_period_markers(text_lower)
    claimed = set()
    results = {}

    for match in matches:
        try:
            cleaned = re.sub(r'[^\d]', '', match.group(1))
            price = int(cleaned)
        except ValueError:
            continue
        if price <= 0:
            continue

        currency = _classify_currency_token(match.group(2))
        found = _closest_unclaimed_period(match, markers, claimed)
        if found is None:
            continue  # без явного периода рядом — не включаем, чтобы не путать с ценой продажи
        m_start, m_end, period = found
        claimed.add(m_start)

        if period not in results:
            results[period] = (price, currency)

    return results

def extract_price_with_type_full(text):
    """Извлечь цену, тип периода, словарь месячных цен и валюту"""
    text_lower = text.lower()
    
    price_dict = extract_monthly_prices(text)
    
    matches = list(re.finditer(_PRICE_TOKEN_RE, text, re.IGNORECASE))
    
    if not matches:
        return None, "не указана", price_dict, None
    
    match = matches[0]
    try:
        cleaned = re.sub(r'[^\d]', '', match.group(1))
        price = int(cleaned)
    except ValueError:
        return None, "не указана", price_dict, None

    currency = _classify_currency_token(match.group(2))
    
    # Тип периода ищем В ОКНЕ РЯДОМ с найденной ценой, ограниченном началом
    # следующей цены — иначе если в сообщении есть вторая цена с другим
    # периодом, первая цена ошибочно подхватывает период второй
    window = _period_window(text_lower, matches, 0)
    period = _detect_period(window, price, currency)

    if period is None:
        # Рядом с ценой ничего не нашли — иногда срок аренды указывают
        # отдельно от конкретной суммы ("сниму на месяц... бюджет 500 евро",
        # а не "500 евро в месяц"). Проверяем текст целиком как запасной
        # вариант, прежде чем скатываться в угадывание по величине суммы
        period = _detect_period(text_lower, price, currency)

    if period is not None:
        price_type = period
    else:
        # Эвристика на случай, когда явного слова-признака периода не нашлось
        # вообще нигде — работает только для EUR/USD (для лиры и неизвестной
        # валюты не гадаем, чтобы не путать дорогую аренду с продажей).
        # Порог 300 — по опыту именно посуточных объявлений в этом рынке:
        # для больших объектов (2+1 и крупнее) настоящая цена за сутки без
        # явной пометки может доходить и до 300, а не только 30-45 как у
        # простых студий
        if currency in ('EUR', 'USD'):
            price_type = "месячная" if price > 300 else "посуточная"
        else:
            price_type = "не указана"
    
    return price, price_type, price_dict, currency

def extract_price_with_type(text):
    """Извлечь цену и определить её тип"""
    price, price_type, _, _ = extract_price_with_type_full(text)
    return price, price_type

# Цена продажи недвижимости на порядки больше цены аренды — если
# "извлечённая цена продажи" подозрительно мала, это почти наверняка не
# цена продажи, а случайно захваченная цена аренды из того же текста
# (например, объявление одновременно рекламирует и продажу, и аренду —
# такое реально встречается, "Срочная продажа 1+1... Аренда 1+1 цена 500$")
SALE_PRICE_SANITY_FLOOR = 3000

def extract_price_and_currency(text):
    """Извлечь цену и валюту для ПРОДАЖИ (без типа периода). Если найденное
    число заведомо мало для цены продажи недвижимости — сообщаем
    "не указана" вместо явно неверного маленького числа."""
    price, _, _, currency = extract_price_with_type_full(text)
    if price is not None and currency in ('EUR', 'USD') and price < SALE_PRICE_SANITY_FLOOR:
        return None, currency
    return price, currency

def extract_price(text):
    """Просто извлечь цену"""
    price, _, _, _ = extract_price_with_type_full(text)
    return price

def get_average_price(price_dict):
    """Получить среднюю цену из словаря месячных цен"""
    if not price_dict:
        return None
    prices = list(price_dict.values())
    return sum(prices) // len(prices) if prices else None

def get_price_range_str(price_dict, currency=None):
    """Получить строку диапазона цен"""
    if not price_dict or len(price_dict) < 2:
        return None
    
    sym = currency_symbol(currency) or '$'
    prices = list(price_dict.values())
    min_price = min(prices)
    max_price = max(prices)
    avg_price = sum(prices) // len(prices)
    
    return f"{min_price}{sym} - {max_price}{sym} (средняя: {avg_price}{sym})"

# Если месяц/день уже прошли в этом году, обычно логично считать, что имеется
# в виду СЛЕДУЮЩИЙ год ("20 августа", когда уже сентябрь, — почти наверняка
# следующий август). НО если дата получается лишь немного в прошлом
# ("28 июля", когда сегодня 4 августа) — это почти наверняка просто
# недавняя дата-ориентир ("ищу квартиру С 28 июля"), а не запрос на
# следующий год. Без этой оговорки такая дата улетала на год вперёд, и
# заявка с ней ошибочно выглядела "стартующей в будущем" — а значит,
# никогда не считалась устаревшей, сколько бы дней ни прошло.
MONTH_ROLLOVER_GRACE_DAYS = 45

def _resolve_year_for_date(now, month, day):
    """Определяет год для даты без явного указания года — с учётом
    'льготного периода' для недавнего прошлого (см. комментарий выше)."""
    year = now.year
    try:
        candidate = datetime(year, month, day).date()
    except ValueError:
        return year
    if candidate < now.date() and (now.date() - candidate).days > MONTH_ROLLOVER_GRACE_DAYS:
        year += 1
    return year

class DateParser:
    def __init__(self):
        self.months_ru = {
            "январ": 1, "февра": 2, "март": 3, "апрел": 4, "мае": 5, "мая": 5,
            "июн": 6, "июл": 7, "авгус": 8, "сентя": 9, "октя": 10, "нояб": 11, "дека": 12
        }
        self.months_short = {
            "янв": 1, "фев": 2, "мар": 3, "апр": 4, "май": 5,
            "июн": 6, "июл": 7, "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12
        }

    def parse_relative_dates(self, text):
        now = datetime.now()
        start_date = now
        end_date = None

        dates_found = []
        
        all_months = {**self.months_ru, **self.months_short}
        for m_name, m_num in all_months.items():
            if m_name in text:
                matches = re.findall(rf'(\d{{1,2}})\s+{m_name}', text)
                for day_str in matches:
                    try:
                        day = int(day_str)
                        year = _resolve_year_for_date(now, m_num, day)
                        dates_found.append(datetime(year, m_num, day).date())
                    except ValueError:
                        pass

        # Сначала ищем даты С ГОДОМ, запоминая их положение в тексте
        full_date_pattern = r'(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})'
        consumed_spans = []
        for match in re.finditer(full_date_pattern, text):
            try:
                day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
                if 1 <= month <= 12 and 1 <= day <= 31:
                    dates_found.append(datetime(year, month, day).date())
                    consumed_spans.append(match.span())
            except ValueError:
                pass

        # Затем даты БЕЗ года — но пропускаем совпадения, которые на самом деле
        # являются началом уже разобранной даты с годом ("20.08" внутри "20.08.2027").
        # Раньше это давало фантомную дату с текущим годом и портило диапазон.
        # ВАЖНО: дефис сюда НЕ включаем — "2-3" почти всегда означает диапазон
        # длительности ("срок 2-3 месяца"), а не дату 2 марта. Раньше это
        # ложно превращало "2-3 месяца" в дату и уводило "с сегодняшнего дня"
        # на совершенно случайный день через полгода.
        short_date_pattern = r'(\d{1,2})[./](\d{1,2})'
        for match in re.finditer(short_date_pattern, text):
            if any(s <= match.start() < e for s, e in consumed_spans):
                continue
            try:
                day, month = int(match.group(1)), int(match.group(2))
                # Та же логика переноса года, что и для дат по имени месяца —
                # с льготным периодом для недавнего прошлого (см. комментарий
                # у _resolve_year_for_date)
                year = _resolve_year_for_date(now, month, day)
                
                if 1 <= month <= 12 and 1 <= day <= 31:
                    dates_found.append(datetime(year, month, day).date())
            except ValueError:
                pass

        dates_found = sorted(list(set(dates_found)))

        if len(dates_found) >= 2:
            start_date = dates_found[0]
            end_date = dates_found[-1]
        elif len(dates_found) == 1:
            start_date = dates_found[0]
            if "длительно" in text or "долгий" in text or "месяц" in text:
                end_date = start_date + timedelta(days=180)
        else:
            if "срочно" in text or "сегодня" in text or "сейчас" in text:
                start_date = now.date()
            elif "завтра" in text:
                start_date = (now + timedelta(days=1)).date()

        return (start_date.date() if isinstance(start_date, datetime) else start_date), end_date

dp = DateParser()

# Кэш собственного ID бота — заполняется в main() при старте,
# чтобы обработчик не дёргал get_me() на каждое сообщение
_bot_own_id = {"id": None}

def username_to_link(username):
    if not username:
        return None
    handle = str(username).lstrip('@').strip()
    if not handle or handle.lower() in ("manual", "система", "нет юзернейма"):
        return None
    return f"https://t.me/{handle}"

def build_text_links(message_link, user_link, chat_title="Чат", user_label="Написать"):
    links = []
    if message_link:
        links.append(f'🔗 <a href="{message_link}">{html.escape(chat_title)}</a>')
    if user_link:
        links.append(f'✉️ <a href="{user_link}">{user_label}</a>')
    if links:
        return " | ".join(links)
    else:
        return "📝 <i>Добавлено вручную через базу</i>"

def _button_label(text, max_len=36):
    """Обрезает подпись кнопки — у Telegram есть ограничение на длину текста
    кнопки, а названия чатов иногда длинные (эмодзи, флаги, полное описание)"""
    text = text or "Источник"
    if len(text) > max_len:
        return text[:max_len - 1].rstrip() + "…"
    return text

async def send_via_bot(chat_id, text, message_link=None, user_link=None, locations=None):
    if chat_id == 0:
        return
    if locations is not None and not location_allowed(locations):
        return
    row = []
    if message_link:
        row.append(Button.url("🔗 Перейти в канал", message_link))
    if user_link:
        row.append(Button.url("✉️ Написать человеку", user_link))
    buttons = [row] if row else None
    try:
        await bot.send_message(chat_id, text, parse_mode='html', link_preview=False, buttons=buttons)
    except Exception as e:
        print(f"❌ Ошибка отправки ботом: {e}")

async def send_via_bot_multi(chat_id, text, button_rows, locations=None, prices=None, rental_period=None):
    """Отправка через бота с НЕСКОЛЬКИМИ рядами кнопок — например, отдельный
    ряд на клиента и отдельный на хозяина в одном мэтче. button_rows — список
    рядов, каждый ряд — список пар (подпись, ссылка); пустые ссылки пропускаются.
    prices — цены обеих сторон мэтча, для фильтра «только с ценой» и для
    границ цены. rental_period — тип периода мэтча ('месячная'/'посуточная'),
    для фильтра по типу аренды и для выбора нужных границ цены. Все три
    фильтра — только тут, а не в send_via_bot: обычные, немэтчевые алерты
    они не затрагивают, только сами мэтчи."""
    if chat_id == 0:
        return
    if locations is not None and not location_allowed(locations):
        return
    if prices is not None and not price_allowed(*prices):
        return
    if rental_period is not None and prices is not None and not price_range_allowed(rental_period, *prices):
        return
    if rental_period is not None and not period_allowed(rental_period):
        return
    buttons = []
    for row_specs in button_rows:
        row = [Button.url(label, url) for label, url in row_specs if url]
        if row:
            buttons.append(row)
    try:
        await bot.send_message(chat_id, text, parse_mode='html', link_preview=False, buttons=buttons or None)
    except Exception as e:
        print(f"❌ Ошибка отправки ботом: {e}")

# ==========================================
# ОБРАБОТКА МЭТЧЕЙ (АРЕНДА И ПРОДАЖА)
# ==========================================
def format_match_price(price, price_type, currency):
    """Безопасное форматирование цены для алертов о мэтчах — раньше None
    отображался буквально как 'None$', а валюта была жёстко зашита"""
    if price is None:
        return "не указана"
    sym = currency_symbol(currency)
    if price_type and price_type != "не указана":
        return f"{price}{sym} ({price_type})"
    return f"{price}{sym}"

async def handle_matches(type_mode, locations, rooms, price, price_type, price_dict, start_date, clean_text, 
                         message_link, user_link, chat_title="Чат", transaction_type="АРЕНДА", 
                         currency=None, end_date=None, all_prices=None, rooms_all=None):
    # Вычисляем один раз здесь, а не в каждом вызывающем месте — так не
    # нужно трогать сигнатуры всех мест, откуда вызывается handle_matches
    # (обработчик Telegram, ВК и т.д.)
    property_category = extract_property_category(clean_text)

    if type_mode == 'demand':
        matches = db.get_matching_supplies(locations, rooms, price, start_date, end_date, price_type,
                                           rooms_all=rooms_all, property_category=property_category)
        if matches:
            for m in matches:
                # Если у объекта указано НЕСКОЛЬКО цен по разным периодам
                # (например, "Краткосрочно 35€ / Долгосрочно 700€") — сначала
                # смотрим, есть ли у него цена именно за период, который
                # ищет клиент, и показываем её. Раньше здесь смотрели только
                # price_dict (это для разных МЕСЯЦЕВ у одного периода, не то
                # же самое) и без него сразу падали на "основную" цену
                # объекта — а она могла относиться к СОВСЕМ ДРУГОМУ периоду
                m_all_prices = m.get('all_prices') or {}
                if price_type in m_all_prices:
                    rel_price, rel_currency = m_all_prices[price_type]
                    owner_price_value = rel_price
                    owner_price_str = format_match_price(rel_price, price_type, rel_currency)
                else:
                    price_range = get_price_range_str(m.get('price_dict'), m.get('currency'))
                    owner_price_value = m['price']
                    owner_price_str = price_range if price_range else format_match_price(m['price'], m.get('price_type'), m.get('currency'))
                client_price_str = format_match_price(price, price_type, currency)
                
                alert = (
                    f"⚡ 🏠 <b>{transaction_type} | АВТО-МЭТЧ: НАЙДЕН ВАРИАНТ ДЛЯ КЛИЕНТА</b>\n"
                    f"📍 {locations_display(locations)} · 📦 {rooms}\n────────────────\n\n"
                    f"🙋‍♂️ <b>Клиент</b> (бюджет до {client_price_str})\n<i>{clean_text[:150]}...</i>\n\n"
                    f"┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n\n"
                    f"🏠 <b>Хозяин</b> (цена {owner_price_str})\n<i>{m['text'][:150]}...</i>"
                )
                button_rows = [
                    [("🔗 " + _button_label(chat_title), message_link), ("✉️ Написать клиенту", user_link)],
                    [("🔗 " + _button_label(m.get('chat_title', 'Чат хозяина')), m.get('link')),
                     ("✉️ Написать хозяину", username_to_link(m.get('user')))],
                ]
                await send_via_bot_multi(RENT_MATCH_CHAT_ID, alert, button_rows, locations=locations,
                                         prices=(price, owner_price_value), rental_period=price_type)

    elif type_mode == 'supply':
        # Если у объекта указано несколько цен по разным периодам (например,
        # и месячная, и суточная) — ищем клиентов под КАЖДЫЙ из периодов,
        # а не только под тот, что определился как "основной"
        periods_to_check = {price_type: (price, currency)}
        if all_prices:
            for p_type, (p_price, p_currency) in all_prices.items():
                periods_to_check[p_type] = (p_price, p_currency)

        seen_demand_keys = set()
        for check_type, (check_price, check_currency) in periods_to_check.items():
            matches = db.get_matching_demands(locations, rooms, check_price, start_date, end_date, check_type,
                                              rooms_all=rooms_all, property_category=property_category)
            for m in matches:
                if m['msg_key'] in seen_demand_keys:
                    continue
                seen_demand_keys.add(m['msg_key'])

                price_range = get_price_range_str(price_dict, check_currency)
                owner_price_str = price_range if price_range else format_match_price(check_price, check_type, check_currency)
                client_price_str = format_match_price(m['price'], m.get('price_type'), m.get('currency'))
                
                alert = (
                    f"⚡ 🏠 <b>{transaction_type} | АВТО-МЭТЧ: НАЙДЕН КЛИЕНТ ПОД ОБЪЕКТ</b>\n"
                    f"📍 {locations_display(locations)} · 📦 {rooms}\n────────────────\n\n"
                    f"🏠 <b>Хозяин</b> (цена {owner_price_str})\n<i>{clean_text[:150]}...</i>\n\n"
                    f"┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n\n"
                    f"🙋‍♂️ <b>Клиент</b> (бюджет до {client_price_str})\n<i>{m['text'][:150]}...</i>"
                )
                button_rows = [
                    [("🔗 " + _button_label(chat_title), message_link), ("✉️ Написать хозяину", user_link)],
                    [("🔗 " + _button_label(m.get('chat_title', 'Чат клиента')), m.get('link')),
                     ("✉️ Написать клиенту", username_to_link(m.get('user')))],
                ]
                await send_via_bot_multi(RENT_MATCH_CHAT_ID, alert, button_rows, locations=locations,
                                         prices=(check_price, m['price']), rental_period=check_type)

    elif type_mode == 'sale_demand':
        matches = db.get_matching_sale_supplies(locations, rooms, price, rooms_all=rooms_all, property_category=property_category)
        if matches:
            for m in matches:
                client_price_str = format_match_price(price, None, currency)
                owner_price_str = format_match_price(m['price'], None, m.get('currency'))
                alert = (
                    f"🏷 <b>ПОКУПКА/ПРОДАЖА | АВТО-МЭТЧ: НАЙДЕН ОБЪЕКТ ДЛЯ ПОКУПАТЕЛЯ</b>\n"
                    f"📍 {locations_display(locations)} · 📦 {rooms}\n────────────────\n\n"
                    f"🧐 <b>Покупатель</b> (бюджет до {client_price_str})\n<i>{clean_text[:150]}...</i>\n\n"
                    f"┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n\n"
                    f"🏢 <b>Продавец</b> (цена {owner_price_str})\n<i>{m['text'][:150]}...</i>"
                )
                button_rows = [
                    [("🔗 " + _button_label(chat_title), message_link), ("✉️ Написать покупателю", user_link)],
                    [("🔗 " + _button_label(m.get('chat_title', 'Чат продавца')), m.get('link')),
                     ("✉️ Написать продавцу", username_to_link(m.get('user')))],
                ]
                await send_via_bot_multi(MATCH_CHAT_ID, alert, button_rows, locations=locations,
                                         prices=(price, m['price']))

    elif type_mode == 'sale_supply':
        matches = db.get_matching_sale_demands(locations, rooms, price, rooms_all=rooms_all, property_category=property_category)
        if matches:
            for m in matches:
                owner_price_str = format_match_price(price, None, currency)
                client_price_str = format_match_price(m['price'], None, m.get('currency'))
                alert = (
                    f"🏷 <b>ПОКУПКА/ПРОДАЖА | АВТО-МЭТЧ: НАЙДЕН ПОКУПАТЕЛЬ ПОД ОБЪЕКТ</b>\n"
                    f"📍 {locations_display(locations)} · 📦 {rooms}\n────────────────\n\n"
                    f"🏢 <b>Продавец</b> (цена {owner_price_str})\n<i>{clean_text[:150]}...</i>\n\n"
                    f"┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n\n"
                    f"🧐 <b>Покупатель</b> (бюджет до {client_price_str})\n<i>{m['text'][:150]}...</i>"
                )
                button_rows = [
                    [("🔗 " + _button_label(chat_title), message_link), ("✉️ Написать продавцу", user_link)],
                    [("🔗 " + _button_label(m.get('chat_title', 'Чат покупателя')), m.get('link')),
                     ("✉️ Написать покупателю", username_to_link(m.get('user')))],
                ]
                await send_via_bot_multi(MATCH_CHAT_ID, alert, button_rows, locations=locations,
                                         prices=(price, m['price']))

def format_duplicate_output(raw_text):
    """Явный вывод для дублей в ручном вводе — раньше в этом случае была полная тишина"""
    preview = raw_text.strip().replace("\n", " ")[:80]
    print(f"\n⚠️  [РУЧНОЙ ВВОД] Дубликат — уже добавлено ранее (в пределах окна дедупликации), пропущено:\n    \"{preview}...\"\n")

def format_console_output(record_type, data):
    """Форматированный вывод в консоль для ручного ввода"""
    locations_str = locations_display(data.get('locations', []))
    rooms_str = data.get('rooms', 'не указана')
    
    output = f"\n📝 [РУЧНОЙ ВВОД] 🏠 ОБЪЕКТ СОХРАНЁН\n"
    output += f"├─ Тип: {record_type}\n"
    output += f"├─ Локация: {locations_str}\n"
    output += f"├─ Комнаты: {rooms_str}\n"
    
    if record_type in ("АРЕНДА", "АРЕНДА (ПОИСК)"):
        price = data.get('price')
        price_type = data.get('price_type', 'не указана')
        price_dict = data.get('price_dict')
        currency = data.get('currency')
        all_prices = data.get('all_prices')
        
        if price_dict and len(price_dict) >= 2:
            price_range = get_price_range_str(price_dict, currency)
            output += f"├─ Цена: {price_range}\n"
        elif all_prices and len(all_prices) >= 2:
            # В сообщении указано несколько цен по разным периодам
            # (например, и месячная, и суточная) — показываем все, а не только первую найденную
            parts = [f"{p}{currency_symbol(c)} ({t})" for t, (p, c) in all_prices.items()]
            output += f"├─ Цена: {' / '.join(parts)}\n"
        else:
            if price:
                output += f"├─ Цена: {price}{currency_symbol(currency)} ({price_type})\n"
            else:
                output += f"├─ Цена: не указана\n"
        
        start = data.get('start', 'не указана')
        end = data.get('end', 'не указана')
        output += f"├─ Доступно с: {start}\n"
        output += f"├─ По: {end}\n"
    
    elif record_type in ("ПРОДАЖА", "ПОКУПКА"):
        price = data.get('price')
        if price:
            output += f"├─ Цена: {price}{currency_symbol(data.get('currency'))}\n"
        else:
            output += f"├─ Цена: не указана\n"
    
    output += f"└─ Статус: ✅ Сохранено\n"
    print(output)

def format_delete_output(msg_key):
    """Форматированный вывод удаления"""
    if msg_key in db.manual_msg_ids:
        record = db.manual_msg_ids[msg_key]
        record_type = "АРЕНДА" if 'price_type' in record else "ПРОДАЖА"
        locations_str = locations_display(record.get('locations', []))
        rooms_str = record.get('rooms', 'не указана')
        
        output = f"\n🗑️ [УДАЛЕНИЕ] ❌ ОБЪЕКТ УДАЛЕН ИЗ БАЗЫ\n"
        output += f"├─ Тип: {record_type}\n"
        output += f"├─ Локация: {locations_str}\n"
        output += f"├─ Комнаты: {rooms_str}\n"
        output += f"└─ Статус: ✅ Удалено\n"
        print(output)
    else:
        print(f"🗑️ Объект удален из базы: {msg_key}")

def _words_near_property(text_lower, action_patterns, window_chars=35):
    """Проверяет, что хотя бы одно предметное слово (квартира/дом/студия/
    вилла/1+1 и т.п. из PROPERTY_WORDS) находится РЯДОМ с хотя бы одним
    словом-действием (сдам/ищу/нужна/куплю/...), а не просто где-то в
    тексте независимо от него. Раньше has_property и has_rent_need
    проверялись по всему сообщению отдельно друг от друга — если в одном
    длинном сообщении встречались оба слова в НЕСВЯЗАННЫХ местах (например,
    "ищу работу... по соседству продаётся дом"), это всё равно засчитывалось
    бы как заявка на недвижимость."""
    action_hits = [m.span() for p in action_patterns for m in re.finditer(p, text_lower)]
    if not action_hits:
        return False
    property_hits = []
    for p in PROPERTY_WORDS:
        for m in re.finditer(p, text_lower):
            # "нужен запас ДЛЯ ДОМА/офиса" — это товар для домашнего
            # использования, а не поиск жилья. "нужна помощь НА ДАЧЕ" —
            # это просьба о помощи В МЕСТЕ, а не поиск самой дачи.
            # "для"/"под"/"на" прямо перед предметным словом почти всегда
            # означает назначение или место действия, а не сам объект
            # недвижимости — не считаем это совпадением
            if re.search(r"\b(?:для|под|на)\s*$", text_lower[:m.start()]):
                continue
            property_hits.append(m.span())
    if not property_hits:
        return False
    for a_start, a_end in action_hits:
        for p_start, p_end in property_hits:
            gap = max(a_start, p_start) - min(a_end, p_end)
            if gap <= window_chars:
                return True
    return False

# ==========================================
# ОСНОВНОЙ ОБРАБОТЧИК
# ==========================================
@client.on(events.NewMessage)
async def my_event_handler(event):
    message = event.message
    chat_id = event.chat_id

    # ✅ НУЛЕВАЯ ПРОВЕРКА: не обрабатывать сообщения в выходных чатах
    # (иначе бот увидит свой же алерт как новое сообщение и повторно его распарсит — зацикливание)
    if chat_id in (MY_CHAT_ID, MATCH_CHAT_ID, RENT_CHAT_ID, RENT_MATCH_CHAT_ID):
        return
    # Доп. защита независимо от .env: личный диалог с ботом — chat_id ЛС всегда
    # равен user id самого бота, так что это сработает, даже если MY_CHAT_ID
    # в .env указан неверно
    if _bot_own_id.get("id") is not None and chat_id == _bot_own_id["id"]:
        return
    # Не обрабатывать сообщения, отправленные самим ботом, где бы они ни всплыли.
    # ВАЖНО: тут нет общей проверки "if event.out" — она блокировала бы вообще
    # любое твоё сообщение в любом чате (включая "Ручной Ввод", где ты —
    # единственный участник и все твои сообщения технически "исходящие").
    # Защиты по chat_id выше уже достаточно для предотвращения зацикливания с ботом.
    if message.sender_id is not None and message.sender_id == _bot_own_id.get("id"):
        return

    if not message.text:
        return

    raw_text = message.text.replace('**', '').replace('__', '')
    text_lower = raw_text.lower()

    is_manual_input = chat_id in (INPUT_CHAT_ID, -1005187082989) and INPUT_CHAT_ID != 0

    # Общие анти-спам фильтры применяем ТОЛЬКО к публичным чатам.
    # В чате "Ручной Ввод" каждое сообщение — осознанное, поэтому фильтровать
    # его теми же эвристиками, что и шумные публичные группы, не нужно —
    # это как раз и делало обработку невидимой ("почему ничего не происходит").
    if not is_manual_input:
        # ✅ ПЕРВАЯ ПРОВЕРКА: дедупликация по контенту (ДЛЯ ВСЕХ ПУБЛИЧНЫХ ЧАТОВ)
        if is_duplicate_content(raw_text):
            return

        # ✅ ВТОРАЯ ПРОВЕРКА: низкий сигнал
        if is_low_signal(raw_text):
            return

        # ✅ ТРЕТЬЯ ПРОВЕРКА: спам слова
        if any(neg_word in text_lower for neg_word in NEGATIVE_WORDS):
            return

    chat = await event.get_chat()
    msg_key = f"{chat_id}_{message.id}"
    
    chat_username = getattr(chat, 'username', None)
    chat_title = getattr(chat, "title", None) or chat_username or f"Чат {chat_id}"
    
    message_link = f"https://t.me/{chat_username}/{message.id}" if chat_username else None
    if not message_link and str(chat_id).startswith("-100"):
        message_link = f"https://t.me/c/{str(chat_id).replace('-100', '')}/{message.id}"
    
    my_locations = detect_locations(raw_text)
    if not my_locations:
        # В названии чата часто указана локация (например, "Махмутлар |
        # Аланья") — если сам текст объявления её не называет, берём из
        # названия группы: это надёжнее, чем оставлять "не указана"
        my_locations = detect_locations(chat_title)

    # РУЧНОЙ ВВОД
    if is_manual_input:
        u_price, u_price_type, u_price_dict, u_currency = extract_price_with_type_full(raw_text)
        u_all_prices = extract_all_period_prices(raw_text)
        u_rooms = extract_rooms(raw_text) or "не указана"
        u_rooms_all = extract_all_rooms(raw_text)
        start_d, end_d = dp.parse_relative_dates(text_lower)

        has_sale_supply_kw = any(re.search(w, text_lower) for w in SALE_SUPPLY_WORDS)
        has_sale_demand_kw = any(re.search(w, text_lower) for w in SALE_DEMAND_WORDS)
        has_rent_need_kw = any(re.search(w, text_lower) for w in RENT_NEED_WORDS)
        # Порог "дорого -> скорее всего продажа" надёжен только для EUR/USD.
        # Суммы в лирах номинально намного больше — обычная аренда легко
        # превышает 15000 TRY/мес и раньше ошибочно улетала в "продажа"
        is_high_price = u_price is not None and u_price >= 15000 and u_currency in ('EUR', 'USD')

        if has_sale_demand_kw:
            # Клиент ищет купить — раньше такие сообщения ошибочно попадали в "продажа"
            is_new = db.add_sale_demand(msg_key, chat_id, "Ручной Ввод", raw_text, "Система", "manual",
                                        None, my_locations, u_rooms, u_price)
            if is_new:
                data = {'locations': my_locations, 'rooms': u_rooms, 'price': u_price, 'currency': u_currency}
                format_console_output("ПОКУПКА", data)
                await handle_matches(
                    'sale_demand', my_locations, u_rooms, u_price, price_type=None, price_dict=None,
                    start_date=None, clean_text=html.escape(raw_text), message_link=None, user_link=None,
                    chat_title="Ручной Ввод", transaction_type="ПОКУПКА/ПРОДАЖА", currency=u_currency, rooms_all=u_rooms_all
                )
            else:
                format_duplicate_output(raw_text)

        elif has_sale_supply_kw or (is_high_price and not has_rent_need_kw):
            is_new = db.add_sale_supply(msg_key, chat_id, "Ручной Ввод", raw_text, "Система", "manual", 
                                        None, my_locations, u_rooms, u_price)
            if is_new:
                data = {
                    'locations': my_locations,
                    'rooms': u_rooms,
                    'price': u_price,
                    'currency': u_currency,
                    'price_type': 'продажа'
                }
                format_console_output("ПРОДАЖА", data)
                await handle_matches(
                    'sale_supply', my_locations, u_rooms, u_price, price_type=None, price_dict=None,
                    start_date=None, clean_text=html.escape(raw_text), message_link=None, user_link=None,
                    chat_title="Ручной Ввод", transaction_type="ПОКУПКА/ПРОДАЖА", currency=u_currency, rooms_all=u_rooms_all
                )
            else:
                format_duplicate_output(raw_text)

        elif has_rent_need_kw:
            # Клиент ищет снять — раньше вообще никак не обрабатывалось в ручном вводе
            is_new = db.add_rent_demand(msg_key, chat_id, "Ручной Ввод", raw_text, "Система", "manual",
                                        None, my_locations, start_d, end_d)
            if is_new:
                data = {
                    'locations': my_locations, 'rooms': u_rooms, 'price': u_price,
                    'currency': u_currency, 'price_type': u_price_type, 'all_prices': u_all_prices,
                    'start': start_d, 'end': end_d
                }
                format_console_output("АРЕНДА (ПОИСК)", data)
                avg_price = get_average_price(u_price_dict) if u_price_dict else u_price
                await handle_matches(
                    'demand', my_locations, u_rooms, avg_price, price_type=u_price_type, price_dict=u_price_dict,
                    start_date=start_d, clean_text=html.escape(raw_text), message_link=None, user_link=None,
                    chat_title="Ручной Ввод", transaction_type="АРЕНДА", currency=u_currency, end_date=end_d,
                    all_prices=u_all_prices, rooms_all=u_rooms_all
                )
            else:
                format_duplicate_output(raw_text)

        else:
            is_new = db.add_rent_supply(msg_key, chat_id, "Ручной Ввод", raw_text, "Система", "manual", 
                                        None, my_locations, start_d, end_d)
            if is_new:
                data = {
                    'locations': my_locations,
                    'rooms': u_rooms,
                    'price': u_price,
                    'currency': u_currency,
                    'price_type': u_price_type,
                    'price_dict': u_price_dict,
                    'all_prices': u_all_prices,
                    'start': start_d,
                    'end': end_d
                }
                format_console_output("АРЕНДА", data)
                avg_price = get_average_price(u_price_dict) if u_price_dict else u_price
                await handle_matches(
                    'supply', my_locations, u_rooms, avg_price, price_type=u_price_type, price_dict=u_price_dict,
                    start_date=start_d, clean_text=html.escape(raw_text), message_link=None, user_link=None,
                    chat_title="Ручной Ввод", transaction_type="АРЕНДА", currency=u_currency, end_date=end_d,
                    all_prices=u_all_prices, rooms_all=u_rooms_all
                )
            else:
                format_duplicate_output(raw_text)
        return

    sender = await event.get_sender()
    sender_name = getattr(sender, 'first_name', '') or ''
    last_name = getattr(sender, 'last_name', '') or ''
    if last_name: 
        sender_name += f" {last_name}"
    username = getattr(sender, 'username', '')
    user_link = f"https://t.me/{username}" if username else None
    
    is_post = getattr(chat, 'broadcast', False) or (event.is_channel and not message.is_reply)
    clean_text = html.escape(raw_text)
    source_prefix = "📢 [ПОСТ]" if is_post else "💬 [КОММЕНТАРИЙ]"

    if is_piano_lesson_request(text_lower):
        alert = f"🎹 <b>{source_prefix} ЗАЯВКА НА ОБУЧЕНИЕ ФОРТЕПИАНО</b>\n────────────────\n🗂 Источник: {chat_title}\n────────────────\n\n{clean_text}"
        await send_via_bot(MY_CHAT_ID, alert, message_link, user_link)
        return

    has_property = any(re.search(w, text_lower) for w in PROPERTY_WORDS)
    has_rent_need = any(re.search(w, text_lower) for w in RENT_NEED_WORDS)
    has_rent_supply = any(re.search(w, text_lower) for w in RENT_SUPPLY_WORDS)
    has_rent_supply_strong = any(re.search(w, text_lower) for w in RENT_SUPPLY_STRONG_WORDS)
    has_sale_supply = any(re.search(w, text_lower) for w in SALE_SUPPLY_WORDS)
    has_sale_demand = any(re.search(w, text_lower) for w in SALE_DEMAND_WORDS)

    # Слово-действие должно быть РЯДОМ с предметным словом (квартира/дом/
    # студия/вилла/...), а не просто где-то в том же сообщении — иначе
    # случайное упоминание "ищу" в одном месте и "дом" в другом, не
    # связанном между собой, тоже считалось бы заявкой
    has_rent_need_near = _words_near_property(text_lower, RENT_NEED_WORDS)
    has_rent_supply_near = _words_near_property(text_lower, RENT_SUPPLY_WORDS)
    has_rent_supply_strong_near = _words_near_property(text_lower, RENT_SUPPLY_STRONG_WORDS)
    has_sale_supply_near = _words_near_property(text_lower, SALE_SUPPLY_WORDS)
    has_sale_demand_near = _words_near_property(text_lower, SALE_DEMAND_WORDS)

    # Инвестиционный маркетинг ("гарантированный доход", ROI) — это не
    # конкретный объект под сдачу/продажу, а презентация комплекса в целом.
    # Отключаем классификацию как ПРЕДЛОЖЕНИЕ для такого текста (спрос,
    # если вдруг совпадёт, не трогаем — это не тот случай)
    if any(re.search(w, text_lower) for w in INVESTMENT_MARKETING_WORDS):
        has_rent_supply_near = False
        has_rent_supply_strong_near = False
        has_sale_supply_near = False

    # "Предлагаю услуги уборки квартир" — это реклама клининга, а не
    # предложение самой недвижимости, хотя "предлагаю" и "квартир"
    # оказываются рядом друг с другом
    if any(re.search(w, text_lower) for w in SERVICE_AD_WORDS):
        has_rent_supply_near = False
        has_rent_supply_strong_near = False

    u_price, u_price_type, u_price_dict, u_currency = extract_price_with_type_full(raw_text)
    u_all_prices = extract_all_period_prices(raw_text)
    u_price_display = f"{u_price}{currency_symbol(u_currency)} ({u_price_type})" if u_price else "не указана"
    # Для продажи период (месячная/посуточная) не имеет смысла —
    # раньше он всё равно печатался у цены продажи ("100000€ (месячная)")
    u_sale_price_display = f"{u_price}{currency_symbol(u_currency)}" if u_price else "не указана"
    u_rooms = extract_rooms(raw_text) or "не указана"
    u_rooms_all = extract_all_rooms(raw_text)
    # Порог "дорого -> скорее всего продажа" надёжен только для EUR/USD —
    # суммы в лирах номинально намного больше, обычная аренда легко
    # превышает 15000 TRY/мес и раньше ошибочно улетала в "продажа"
    is_high_price = (u_price is not None and u_price >= 15000 and u_currency in ('EUR', 'USD'))

    # КУПЛЯ-ПРОДАЖА
    if has_sale_supply_near or has_sale_demand_near or (has_property and is_high_price):
        sale_direction = _resolve_sale_direction(text_lower, has_sale_supply_near, has_sale_demand_near)
        if sale_direction == 'sale_demand':
            if is_semantic_duplicate('sale_demand', my_locations, None, None, u_sale_price_display, u_rooms, "продажа"):
                return
            is_new = db.add_sale_demand(msg_key, chat_id, chat_title, raw_text, sender_name, username, 
                                        message_link, my_locations, u_rooms, u_price)
            if is_new:
                alert = (
                    f"🧐 <b>{source_prefix} ПОИСК НА ПОКУПКУ НЕДВИЖИМОСТИ</b>\n────────────────\n"
                    f"📍 Локация: {locations_display(my_locations)}\n💰 Бюджет: {u_sale_price_display} | 📦 Комнат: {u_rooms}\n"
                    f"🗂 Источник: {chat_title}\n────────────────\n\n{clean_text}"
                )
                await send_via_bot(MY_CHAT_ID, alert, message_link, user_link, locations=my_locations)
                await handle_matches(
                    'sale_demand', my_locations, u_rooms, u_price, price_type=None, price_dict=None,
                    start_date=None, clean_text=clean_text, message_link=message_link, user_link=user_link,
                    chat_title=chat_title, transaction_type="ПОКУПКА/ПРОДАЖА", currency=u_currency, rooms_all=u_rooms_all
                )
            return
        else:
            if is_semantic_duplicate('sale_supply', my_locations, None, None, u_sale_price_display, u_rooms, "продажа"):
                return
            is_new = db.add_sale_supply(msg_key, chat_id, chat_title, raw_text, sender_name, username, 
                                        message_link, my_locations, u_rooms, u_price)
            if is_new:
                alert = (
                    f"🏢 <b>{source_prefix} ПРОДАЖА ОТ СОБСТВЕННИКА / АГЕНТА</b>\n────────────────\n"
                    f"📍 Локация: {locations_display(my_locations)}\n💰 Цена: {u_sale_price_display} | 📦 Комнат: {u_rooms}\n"
                    f"🗂 Источник: {chat_title}\n────────────────\n\n{clean_text}"
                )
                await send_via_bot(MY_CHAT_ID, alert, message_link, user_link, locations=my_locations)
                await handle_matches(
                    'sale_supply', my_locations, u_rooms, u_price, price_type=None, price_dict=None,
                    start_date=None, clean_text=clean_text, message_link=message_link, user_link=user_link,
                    chat_title=chat_title, transaction_type="ПОКУПКА/ПРОДАЖА", currency=u_currency, rooms_all=u_rooms_all
                )
            return

    # АРЕНДА
    if has_rent_need_near or has_rent_supply_near:
        start_d, end_d = dp.parse_relative_dates(text_lower)
        date_str = f"{start_d if start_d else 'не указаны'} -> {end_d if end_d else 'не указаны'}"
        rent_direction = _resolve_rent_direction(text_lower, has_rent_supply_near, has_rent_need_near)

        if rent_direction == 'rent_demand':
            # Направление уже решено выше через _resolve_rent_direction —
            # при совпадении обоих признаков сразу побеждает тот, что
            # встретился РАНЬШЕ по тексту (как и в продаже/покупке)
            if is_semantic_duplicate('rent_demand', my_locations, start_d, end_d, u_price_display, u_rooms, u_price_type):
                return
            is_new = db.add_rent_demand(msg_key, chat_id, chat_title, raw_text, sender_name, username, 
                                        message_link, my_locations, start_d, end_d)
            if is_new:
                alert = (
                    f"🙋‍♂️ <b>{source_prefix} КЛИЕНТ ИЩЕТ АРЕНДУ</b>\n────────────────\n"
                    f"📍 Локация: {locations_display(my_locations)}\n📆 Даты: {date_str}\n"
                    f"💰 Бюджет: {u_price_display} | 📦 Комнат: {u_rooms}\n"
                    f"🗂 Источник: {chat_title}\n────────────────\n\n{clean_text}"
                )
                await send_via_bot(RENT_CHAT_ID, alert, message_link, user_link, locations=my_locations)
                avg_price = get_average_price(u_price_dict) if u_price_dict else u_price
                await handle_matches(
                    'demand', my_locations, u_rooms, avg_price, price_type=u_price_type, price_dict=u_price_dict,
                    start_date=start_d, clean_text=clean_text, message_link=message_link, user_link=user_link,
                    chat_title=chat_title, transaction_type="АРЕНДА", currency=u_currency, end_date=end_d,
                    all_prices=u_all_prices, rooms_all=u_rooms_all
                )
            return

        elif rent_direction == 'rent_supply':
            if is_semantic_duplicate('rent_supply', my_locations, start_d, end_d, u_price_display, u_rooms, u_price_type):
                return
            is_new = db.add_rent_supply(msg_key, chat_id, chat_title, raw_text, sender_name, username, 
                                        message_link, my_locations, start_d, end_d)
            if is_new:
                if u_all_prices and len(u_all_prices) >= 2:
                    price_line = " / ".join(f"{p}{currency_symbol(c)} ({t})" for t, (p, c) in u_all_prices.items())
                else:
                    price_line = u_price_display
                alert = (
                    f"🏠 <b>{source_prefix} ХОЗЯИН СДАЕТ НЕДВИЖИМОСТЬ</b>\n────────────────\n"
                    f"📍 Локация: {locations_display(my_locations)}\n📆 Доступно с: {start_d if start_d else 'не указано'}\n"
                    f"💰 Цена: {price_line} | 📦 Комнат: {u_rooms}\n"
                    f"🗂 Источник: {chat_title}\n────────────────\n\n{clean_text}"
                )
                await send_via_bot(RENT_CHAT_ID, alert, message_link, user_link, locations=my_locations)
                avg_price = get_average_price(u_price_dict) if u_price_dict else u_price
                await handle_matches(
                    'supply', my_locations, u_rooms, avg_price, price_type=u_price_type, price_dict=u_price_dict,
                    start_date=start_d, clean_text=clean_text, message_link=message_link, user_link=user_link,
                    chat_title=chat_title, transaction_type="АРЕНДА", currency=u_currency, end_date=end_d,
                    all_prices=u_all_prices, rooms_all=u_rooms_all
                )
            return

@client.on(events.MessageDeleted)
async def on_message_deleted(event):
    """Обработка удаления сообщений из чата ручного ввода"""
    try:
        deleted_ids = event.deleted_ids
        chat_id = event.chat_id
        candidate_chat_ids = [c for c in (INPUT_CHAT_ID, -1005187082989) if c]

        for msg_id in deleted_ids:
            found = False
            if chat_id is not None:
                # Супергруппа/канал — chat_id есть в событии, проверяем как обычно
                if chat_id not in candidate_chat_ids:
                    continue
                msg_key = f"{chat_id}_{msg_id}"
                if msg_key in db.manual_msg_ids:
                    db.remove_by_msg_key(msg_key)
                    format_delete_output(msg_key)
                    found = True
            else:
                # Обычная (не супер-) группа — Telegram не передаёт chat_id при удалении,
                # поэтому ищем совпадение среди известных ключей ручного ввода
                for cid in candidate_chat_ids:
                    msg_key = f"{cid}_{msg_id}"
                    if msg_key in db.manual_msg_ids:
                        db.remove_by_msg_key(msg_key)
                        format_delete_output(msg_key)
                        found = True
                        break
            if not found:
                print(f"🗑️  Удалено сообщение (ID {msg_id}), но записи в базе не было "
                      f"(сообщение не сохранялось — было дублем или не прошло критерии)")
    except Exception as e:
        print(f"❌ Ошибка при обработке удаления: {e}")

async def main():
    loaded = 0
    # Дедуп из старых запусков учитываем только за последние 24 часа —
    # иначе тестовые/повторные тексты блокируются навсегда
    for msg_key, content_hash in dedup_conn.execute(
        "SELECT msg_key, content_hash FROM sent_log WHERE ts >= datetime('now', '-1 day') "
        "ORDER BY ts DESC LIMIT ?", (MAX_FINGERPRINTS,)
    ):
        db.processed_msgs.add(msg_key)
        db.content_hashes.add(content_hash)
        loaded += 1
    # Чистим совсем старые записи, чтобы файл не разрастался бесконечно
    try:
        dedup_conn.execute("DELETE FROM sent_log WHERE ts < datetime('now', '-30 days')")
        dedup_conn.execute("DELETE FROM records WHERE ts < datetime('now', '-90 days')")
        dedup_conn.commit()
    except Exception:
        pass

    # Восстанавливаем сами объекты (не только отпечатки) — без этого база
    # для мэтчинга после каждого перезапуска была бы пустой, и вручную
    # добавленные объекты переставали бы участвовать в мэтчинге
    records_loaded = load_full_records()
    expired_on_start = cleanup_expired_records()
    await _load_disabled_locations()
    await _load_require_price()
    await _load_rental_period_filter()
    await _load_price_range_settings()

    await asyncio.gather(
        client.start(),
        bot.start(bot_token=BOT_TOKEN)
    )
    bot_me = await bot.get_me()
    client_me = await client.get_me()
    _bot_own_id["id"] = bot_me.id
    # Постоянная кнопка "⚙️ Настройки" внизу экрана — во все чаты, куда
    # приходят алерты. Функция сама пропускает чат, если кнопка там уже
    # была отправлена раньше (не шлётся заново при каждом перезапуске)
    for dest_chat_id in {MY_CHAT_ID, RENT_CHAT_ID, MATCH_CHAT_ID, RENT_MATCH_CHAT_ID}:
        await _ensure_settings_keyboard(dest_chat_id)
    asyncio.create_task(heartbeat_loop())
    asyncio.create_task(expiry_cleanup_loop())
    asyncio.create_task(self_healing_loop())
    asyncio.create_task(vk_poll_loop())
    asyncio.create_task(miniapp_sync_loop())
    print("🚀 Парсер запущен со всеми мэтчами, динамическими ценами и поддержкой нескольких локаций!")
    print(f"🔑 Отпечаток файла: {SCRIPT_FINGERPRINT}  (сверяй с тем, что называет Claude, чтобы убедиться, что запущена последняя версия)")
    print("📝 Отслеживание удаления объектов включено!")
    print(f"💾 Дедупликация теперь сохраняется на диск (загружено {loaded} записей из предыдущих запусков)")
    print(f"📦 Объекты восстановлены из базы: аренда-спрос {records_loaded['rent_demand']}, "
          f"аренда-предложение {records_loaded['rent_supply']}, "
          f"продажа-спрос {records_loaded['sale_demand']}, "
          f"продажа-предложение {records_loaded['sale_supply']}")
    if expired_on_start:
        print(f"🧹 Из них сразу удалено как просроченные (даты уже прошли): {len(expired_on_start)}")
    if DISABLED_LOCATIONS:
        print(f"🗺 Скрыто через /settings: {len(DISABLED_LOCATIONS)} (напиши /settings боту, чтобы изменить)")
    if UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN:
        print(f"🔗 Мини-апп настроек подключён (синхронизация каждые {MINIAPP_SYNC_INTERVAL_SECONDS} сек)")
    if MY_CHAT_ID != client_me.id:
        print(f"⚠️  ВНИМАНИЕ: MY_CHAT_ID в .env ({MY_CHAT_ID}) НЕ совпадает с твоим собственным id ({client_me.id}).")
        print(f"    Бот шлёт алерты ЛИЧНО тебе, поэтому MY_CHAT_ID должен быть равен id аккаунта, "
              f"под которым запущен парсер — то есть {client_me.id}.")
    if RENT_CHAT_ID != MY_CHAT_ID:
        try:
            await bot.get_entity(RENT_CHAT_ID)
        except Exception as e:
            print(f"⚠️  ВНИМАНИЕ: бот не может получить доступ к RENT_CHAT_ID ({RENT_CHAT_ID}): {e}")
            print(f"    Скорее всего, бота нужно добавить в этот чат как участника — иначе отправка алертов "
                  f"по аренде туда будет молча падать.")
    if RENT_MATCH_CHAT_ID != MATCH_CHAT_ID:
        try:
            await bot.get_entity(RENT_MATCH_CHAT_ID)
        except Exception as e:
            print(f"⚠️  ВНИМАНИЕ: бот не может получить доступ к RENT_MATCH_CHAT_ID ({RENT_MATCH_CHAT_ID}): {e}")
            print(f"    Скорее всего, бота нужно добавить в этот чат как участника, либо ID в .env указан "
                  f"не в том формате (сверь через find_rent_chat_id.py).")
    print()
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
