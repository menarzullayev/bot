# bot/plugins/admin/network_cmds.py
"""
Tarmoq diagnostikasi va yordamchi vositalari uchun mo'ljallangan
admin plaginlari.
"""
import asyncio
import html
import io
import shlex
import time
from typing import Optional

# Qo'shimcha kutubxonalarni xavfsiz import qilish
try:
    import httpx
except ImportError:
    httpx = None

try:
    import speedtest
except ImportError:
    speedtest = None

try:
    import whois
except ImportError:
    whois = None

try:
    import dns.resolver
except ImportError:
    dns = None

from loguru import logger
from telethon.tl.custom import Message

from core.app_context import AppContext
from bot.decorators import userbot_cmd
from bot.lib.auth import admin_only
from bot.lib.system import run_shell_command
from bot.lib.ui import animate_message, format_error, send_as_file_if_long, managed_animation
from bot.lib.telegram import edit_message
from bot.lib.utils import humanbytes

ERROR_PSUTIL_NOT_INSTALLED = "<b>⚠️ Xatolik:</b> `psutil` kutubxonasi o'rnatilmagan."
STATE_KEY_SPEEDTEST = "speedtest.is_running"


@userbot_cmd(command="http", description="URL manzilning HTTP statusini va sarlavhalarini tekshiradi.")
@admin_only
async def http_status_handler(event: Message, context: AppContext):
    """.http google.com"""
    if not httpx:
        return await event.edit(format_error("`httpx` kutubxonasi o'rnatilmagan."), parse_mode='html')

    if not event.text:
        return
    url = event.text.split(maxsplit=1)[1] if len(event.text.split()) > 1 else ""
    if not url:
        return await event.edit(format_error("URL manzil kiriting."), parse_mode='html')
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    await event.edit(f"<code>GET {html.escape(url)}...</code>", parse_mode='html')
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
            start_time = time.monotonic()
            resp = await client.head(url)
            duration = (time.monotonic() - start_time) * 1000

        res_text = f"<b>🌐 HTTP Status:</b> <code>{html.escape(url)}</code>\n\n" f"<b>Status:</b> <code>{resp.status_code} {resp.reason_phrase}</code>\n" f"<b>Javob:</b> <code>{duration:.2f} ms</code>\n\n" "<b>Sarlavhalar:</b>\n"
        headers_str = "".join(f"• <code>{k}: {v}</code>\n" for k, v in resp.headers.items())
        await send_as_file_if_long(event, res_text + headers_str, filename="http_headers.txt")
    except httpx.RequestError as err:
        await event.edit(format_error(f"HTTP so'rovida xato:\n<code>{html.escape(str(err))}</code>"), parse_mode='html')
    except Exception as err:
        await event.edit(format_error(f"Noma'lum xato:\n<code>{html.escape(str(err))}</code>"), parse_mode='html')


@userbot_cmd(command="speedtest", description="Serverning internet tezligini tekshiradi.")
@admin_only
async def speedtest_handler(event: Message, context: AppContext):
    if not speedtest or not httpx:
        return await event.edit(format_error("`speedtest-cli` va `httpx` kutubxonalari o'rnatilmagan."), parse_mode='html')

    if context.state.get(STATE_KEY_SPEEDTEST):
        return await event.edit("<b>⏳ Speedtest allaqachon ishlamoqda. Iltimos, kuting.</b>", parse_mode='html')

    await context.state.set(STATE_KEY_SPEEDTEST, True)
    msg = await event.edit("<code>🚀 Tezlik tekshirilmoqda...</code>", parse_mode='html')
    anim_task = None
    try:
        loop = asyncio.get_running_loop()
        s = await loop.run_in_executor(None, speedtest.Speedtest)

        anim_task = await animate_message(msg, "Server tanlanmoqda")
        await loop.run_in_executor(None, s.get_best_server)
        if anim_task: anim_task.cancel()

        anim_task = await animate_message(msg, "Yuklab olish")
        await loop.run_in_executor(None, s.download)
        if anim_task: anim_task.cancel()

        anim_task = await animate_message(msg, "Yuklash")
        await loop.run_in_executor(None, s.upload)
        if anim_task: anim_task.cancel()

        res = s.results
        share_link = await loop.run_in_executor(None, res.share)
        
        await msg.edit("<code>🖼️ Natija rasmi tayyorlanmoqda...</code>", parse_mode='html')
        
        # YECHIM: So'rovni brauzer so'roviga o'xshatish uchun User-Agent qo'shamiz
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        async with httpx.AsyncClient() as client:
            img_resp = await client.get(share_link, headers=headers, follow_redirects=True)

        caption = (
            "<b>⚡️ Speedtest Natijalari</b>\n\n"
            f"<b>Server:</b> <code>{html.escape(res.server['name'])} ({html.escape(res.server['country'])})</code>\n"
            f"<b>Ping:</b> <code>{res.ping:.2f} ms</code>\n"
            f"<b>📥 Yuklab olish:</b> <code>{humanbytes(res.download)}/s</code>\n"
            f"<b>📤 Yuklash:</b> <code>{humanbytes(res.upload)}/s</code>"
        )
        
        if event.client and img_resp.status_code == 200 and 'image' in img_resp.headers.get('content-type', ''):
            # Animatsiya xabarini o'chiramiz
            await msg.delete()

            # YECHIM: Rasm ma'lumotlarini fayl obyektiga o'rab, unga nom beramiz
            with io.BytesIO(img_resp.content) as img_stream:
                img_stream.name = "speedtest.png"
                await event.client.send_file(
                    event.chat_id,
                    file=img_stream,
                    caption=caption,
                    reply_to=event.id,
                    parse_mode='html'
                )

        else:
            # Agar shunda ham rasm yuklanmasa, bu haqida aniq xabar beramiz
            error_caption = caption + f"\n\n⚠️ <b>Izoh:</b> <code>Natija rasmini yuklab bo'lmadi (Status: {img_resp.status_code}).</code>"
            await msg.edit(error_caption, link_preview=False, parse_mode='html')

    except Exception as err:
        logger.exception("Speedtestda xato")
        await msg.edit(format_error(f"Speedtestda xato: {type(err).__name__}: {html.escape(str(err))}"), parse_mode='html')
    finally:
        if anim_task and not anim_task.done():
            anim_task.cancel()
        await context.state.delete(STATE_KEY_SPEEDTEST)

@userbot_cmd(command="whois", description="Domen yoki IP haqida WHOIS ma'lumotini oladi.")
@admin_only
async def whois_handler(event: Message, context: AppContext):
    if not whois:
        return await event.edit(format_error("`python-whois` kutubxonasi o'rnatilmagan."), parse_mode='html')

    if not event.text:
        return
    domain = event.text.split(maxsplit=1)[1] if len(event.text.split()) > 1 else ""
    if not domain:
        return await event.edit(format_error("Domen yoki IP manzil kiriting."), parse_mode='html')

    await event.edit(f"<code>🔄 {html.escape(domain)} uchun WHOIS olinmoqda...</code>", parse_mode='html')
    try:
        w_info_obj = await asyncio.to_thread(whois.whois, domain)
        w_info = dict(w_info_obj) if w_info_obj else {}

        if not w_info:
            return await event.edit(format_error(f"<code>{domain}</code> uchun WHOIS ma'lumoti topilmadi."), parse_mode='html')

        res = f"<b>ℹ️ WHOIS: {html.escape(domain)}</b>\n\n"
        for k, v in w_info.items():
            if v:
                val_str = ", ".join(map(str, v)) if isinstance(v, list) else str(v)
                res += f"<b>{html.escape(str(k)).capitalize()}:</b> <code>{html.escape(val_str)}</code>\n"

        await send_as_file_if_long(event, res, filename="whois_result.txt")
    except Exception as err:
        await event.edit(format_error(f"WHOIS xatosi: {err}"), parse_mode='html')


@userbot_cmd(command="dns", description="Domen uchun DNS yozuvlarini tekshiradi.")
@admin_only
async def dns_lookup_handler(event: Message, context: AppContext):
    if not dns:
        return await event.edit(format_error("`dnspython` kutubxonasi o'rnatilmagan."), parse_mode='html')

    if not event.text:
        return
    domain = event.text.split(maxsplit=1)[1] if len(event.text.split()) > 1 else ""
    if not domain:
        return await event.edit(format_error("Domen nomini kiriting."), parse_mode='html')

    await event.edit(f"<code>🔄 {html.escape(domain)} DNS yozuvlari olinmoqda...</code>", parse_mode='html')

    def get_dns_records_sync(domain_name: str) -> str:
        if not dns:
            return ""
        res = ""
        for rtype in ["A", "AAAA", "MX", "CNAME", "TXT", "NS"]:
            try:
                answers = dns.resolver.resolve(domain_name, rtype)
                res += f"\n<b>{rtype} Records:</b>\n"
                res += "".join(f"   • <code>{html.escape(rdata.to_text())}</code>\n" for rdata in answers)
            except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.NoNameservers):
                pass
            except Exception as e:
                logger.warning(f"DNS lookup error for {domain_name} ({rtype}): {e}")
        return res

    try:
        dns_res = await asyncio.to_thread(get_dns_records_sync, domain)
        if not dns_res:
            return await event.edit(format_error(f"<code>{domain}</code> uchun DNS yozuvlari topilmadi."), parse_mode='html')
        await event.edit(f"<b>🌐 DNS Lookup: {html.escape(domain)}</b>\n{dns_res}", parse_mode='html')
    except Exception as err:
        await event.edit(format_error(f"DNS xatosi: {err}"), parse_mode='html')
