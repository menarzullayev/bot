# userbot-v0/bot/plugins/user/profile.py
"""
Profilni boshqarish (ism, bio, rasm, maxfiylik va hk) uchun plagin.
(To'liq modernizatsiya qilingan).
"""

import asyncio
import html
import io
import uuid
from typing import List, Optional, Union, cast

from loguru import logger
from telethon import functions, types
from telethon.tl.custom import Message
from telethon.tl.functions.account import (GetAuthorizationsRequest,
                                            ResetAuthorizationRequest,
                                            SetPrivacyRequest,
                                            UpdateProfileRequest,
                                            UpdateUsernameRequest)
from telethon.tl.functions.contacts import (BlockRequest, DeleteContactsRequest,
                                             GetBlockedRequest, UnblockRequest)
from telethon.tl.functions.photos import (DeletePhotosRequest,
                                           UploadProfilePhotoRequest)
from telethon.tl.types import InputPhoto, InputPrivacyKeyStatusTimestamp, InputPrivacyKeyProfilePhoto, InputPrivacyKeyPhoneNumber, InputPrivacyKeyForwards, InputPrivacyValueAllowAll, InputPrivacyValueAllowContacts, InputPrivacyValueDisallowAll, InputPrivacyValueAllowUsers, InputPrivacyValueDisallowUsers
from telethon.errors.rpcerrorlist import RPCError, UsernameInvalidError

from core.app_context import AppContext
from bot.decorators import userbot_cmd
from bot.lib.auth import admin_only
from bot.lib.telegram import get_account_id, get_display_name, get_extended_user_info, get_user
from bot.lib.ui import (PaginationHelper, code, format_error,
                        format_success, bold)


# --- YORDAMCHI FUNKSIYALAR ---

async def _call_and_handle_errors(event: Message, coro, success_msg: str):
    """Telethon so'rovlarini xatoliklarni ushlagan holda chaqiradi va javobni tahrirlaydi."""
    try:
        await coro
        await event.edit(success_msg, parse_mode='html')
    except UsernameInvalidError:
        error_text = format_error("Bu username band yoki Telegram qoidalariga mos kelmaydi.")
        await event.edit(error_text, parse_mode='html')
    except Exception as e:
        error_message = str(e)
        if 'The username is already taken' in error_message:
            error_message = "Bu username allaqachon band."
        logger.error(f"Profilni boshqarishda xatolik: {error_message}")
        await event.edit(format_error(html.escape(error_message)), parse_mode='html')

async def _save_snapshot(context: AppContext, account_id: int, name: str, client):
    """Joriy profil holatini (rasm, ism, bio) ma'lumotlar bazasiga saqlaydi."""
    me = await client.get_me()
    if not isinstance(me, types.User): return

    photo_blob = await client.download_profile_photo('me', file=bytes)
    user_info = await get_extended_user_info(context, client, me.id)
    current_bio = user_info.get('bio', '') if user_info else ''

    await context.db.execute(
        "REPLACE INTO profile_snapshots (account_id, snapshot_name, first_name, last_name, bio, photo_blob) VALUES (?, ?, ?, ?, ?, ?)",
        (account_id, name, me.first_name, me.last_name, current_bio, photo_blob)
    )

# --- PROFILNI O'ZGARTIRISH ---

@userbot_cmd(command="set", description="Profil ma'lumotlarini (ism, bio, username) o'zgartiradi.")
@admin_only
async def profile_setter(event: Message, context: AppContext):
    if not event.text or not event.client: return
    parts = event.text.split(maxsplit=2)
    if len(parts) < 2:
        return await event.edit(format_error("Format: <code>.set name|bio|username &lt;qiymat&gt;</code>"), parse_mode='html')

    command = parts[1].lower()
    value = parts[2].strip() if len(parts) > 2 else ""

    if not value and command != 'bio':
        return await event.edit(format_error(f"Yangi {code(command)} uchun matn kiriting."), parse_mode='html')

    request, success_msg = None, f"✅ <b>{command.capitalize()}</b> muvaffaqiyatli o'zgartirildi."
    if command == "name":
        first_name, *last_name_parts = value.split('|', 1)
        request = UpdateProfileRequest(first_name=first_name.strip(), last_name=(last_name_parts[0].strip() if last_name_parts else ""))
    elif command == "bio":
        request = UpdateProfileRequest(about=value)
    elif command == "username":
        if not value: return await event.edit(format_error("Username bo'sh bo'lishi mumkin emas."), parse_mode='html')
        request = UpdateUsernameRequest(username=value)
        success_msg = format_success(f"Username o'zgartirildi: {code('@' + value)}")
    else:
        return await event.edit(format_error(f"Noma'lum sozlama: `{command}`. Mavjudlari: name, bio, username."), parse_mode='html')
    
    await _call_and_handle_errors(event, event.client(request), success_msg)

@userbot_cmd(command="setpfp", description="Javob berilgan rasmni profil rasmiga o'rnatadi.")
@admin_only
async def set_pfp(event: Message, context: AppContext):
    if not event.client: return
    if not (replied := await event.get_reply_message()) or not replied.photo:
        return await event.edit(format_error("Rasmga javob bering."), parse_mode='html')

    await event.edit("<i>🔄 Profil rasmi o'rnatilmoqda...</i>", parse_mode='html')
    pfp_file = await event.client.upload_file(await replied.download_media())
    coro = event.client(UploadProfilePhotoRequest(file=pfp_file))
    await _call_and_handle_errors(event, coro, format_success("Profil rasmi o'rnatildi."))

@userbot_cmd(command="delpfp", description="Profil rasmlarini o'chiradi (1 yoki barchasini).")
@admin_only
async def del_pfp(event: Message, context: AppContext):
    if not event.client or not event.text or not event.sender_id: return
    args = (event.text.split(maxsplit=1) + [""])[1].strip().lower()

    await event.edit("<i>🔄 Profil rasmlari tekshirilmoqda...</i>", parse_mode='html')
    pfp_list = await event.client.get_profile_photos('me')
    if not pfp_list:
        return await event.edit("ℹ️ Profil rasmlari mavjud emas.", parse_mode='html')

    photos_to_delete = []
    if not args or args == '1':
        photos_to_delete.append(pfp_list[0])
    elif args.startswith("all --confirm"):
        confirm_code = args.split()[-1]
        confirm_key = f"confirm_delpfp:{event.sender_id}"
        if confirm_code != context.state.get(confirm_key):
            return await event.edit(format_error("Tasdiqlash kodi xato yoki vaqti o'tgan."), parse_mode='html')
        await context.state.delete(confirm_key)
        photos_to_delete.extend(pfp_list)
    elif args == 'all':
        confirm_code = str(uuid.uuid4().hex[:6])
        confirm_key = f"confirm_delpfp:{event.sender_id}"
        await context.state.set(confirm_key, confirm_code, ttl_seconds=30)
        prompt = (f"⚠️ <b>DIQQAT!</b> Siz barcha profil rasmlarini o'chiryapsiz.\n"
                  f"✅ Davom etish uchun <b>30 soniya ichida</b> quyidagi buyruqni yuboring:\n"
                  f"<code>.delpfp all --confirm {confirm_code}</code>")
        return await event.edit(prompt, parse_mode='html')
    else:
        return await event.edit(format_error(f"Noto'g'ri argument. Mavjud: {code('1')} yoki {code('all')}"), parse_mode='html')

    if photos_to_delete:
        input_photos = [InputPhoto(p.id, p.access_hash, p.file_reference) for p in photos_to_delete]
        coro = event.client(DeletePhotosRequest(id=cast(List[types.TypeInputPhoto], input_photos)))
        await _call_and_handle_errors(event, coro, format_success(f"{len(input_photos)} ta profil rasmi o'chirildi."))

@userbot_cmd(command="clone", description="Boshqa foydalanuvchi profilini klonlaydi.")
@admin_only
async def clone_profile(event: Message, context: AppContext):
    if not event.client: return
    
    args = ((event.text or "").split(maxsplit=1) + [""])[1].strip()
    
    target_user, error = await get_user(context, event, args)
    if error or not target_user:
        return await event.edit(error or format_error("Foydalanuvchi topilmadi."), parse_mode='html')
    if not isinstance(target_user, types.User):
        return await event.edit(format_error("Klonlash uchun faqat foydalanuvchi profili ko'rsatilishi mumkin."), parse_mode='html')

    await event.edit(f"<i>🔄 {get_display_name(target_user)} profili klonlanmoqda...</i>", parse_mode='html')
    try:
        user_info = await get_extended_user_info(context, event.client, target_user.id)
        bio = user_info.get('bio', '') if user_info else ''
        
        await event.client(UpdateProfileRequest(first_name=target_user.first_name, last_name=target_user.last_name or "", about=bio))
        
        if target_user.photo:
            if pfp_bytes := await event.client.download_profile_photo(target_user, file=bytes):
                pfp_file = await event.client.upload_file(pfp_bytes)
                await event.client(UploadProfilePhotoRequest(file=pfp_file))
        
        await event.edit(format_success("Profil muvaffaqiyatli klonlandi!"), parse_mode='html')
    except Exception as e:
        logger.exception(f"Klonlashda xatolik: {e}")
        await event.edit(format_error(f"Klonlashda xatolik: {html.escape(str(e))}"), parse_mode='html')


@userbot_cmd(command="anon", description="Anonim rejimni yoqadi/o'chiradi.")
@admin_only
async def anon_mode(event: Message, context: AppContext):
    if not event.client or not event.text: return
    args = (event.text.split(maxsplit=1) + [""])[1].strip().lower()
    account_id = await get_account_id(context, event.client)
    if not account_id: return await event.edit(format_error("Akkaunt ID topilmadi."), parse_mode='html')
    
    if args == "on":
        await _save_snapshot(context, account_id, "__anon_backup", event.client)
        if pfp_list := await event.client.get_profile_photos('me'):
            await event.client(DeletePhotosRequest(id=[InputPhoto(p.id, p.access_hash, p.file_reference) for p in pfp_list]))
        coro = event.client(UpdateProfileRequest(first_name=".", last_name="", about=""))
        await _call_and_handle_errors(event, coro, format_success("Anonim rejim yoqildi."))
    elif args == "off":
        snapshot = await context.db.fetchone("SELECT * FROM profile_snapshots WHERE account_id = ? AND snapshot_name = '__anon_backup'", (account_id,))
        if not snapshot:
            return await event.edit(format_error("Anonim rejim uchun zaxira topilmadi."), parse_mode='html')
        
        await event.client(UpdateProfileRequest(first_name=snapshot['first_name'], last_name=snapshot['last_name'], about=snapshot['bio']))
        if snapshot['photo_blob']:
            pfp_file = await event.client.upload_file(snapshot['photo_blob'])
            await event.client(UploadProfilePhotoRequest(file=pfp_file))
        await event.edit(format_success("Anonim rejim o'chirildi."), parse_mode='html')
    else:
        await event.edit(format_error("Noto'g'ri argument. Mavjud: `on` yoki `off`"), parse_mode='html')

@userbot_cmd(command="profile", description="Profil holatini saqlaydi va boshqaradi.")
@admin_only
async def snapshot_manager(event: Message, context: AppContext):
    if not event.client or not event.text: return
    account_id = await get_account_id(context, event.client)
    if not account_id: return await event.edit(format_error("Akkaunt ID topilmadi."), parse_mode='html')

    parts = event.text.split(maxsplit=2)
    if len(parts) < 2: return await event.edit(format_error("Foydalanish: `.profile save|load|list|del [nom]`"), parse_mode='html')
    
    command = parts[1].lower()
    name = parts[2].strip() if len(parts) > 2 else ""

    if command in ("save", "load", "del") and not name:
        return await event.edit(format_error(f"ⓘ {code(command)} uchun nom kiriting."), parse_mode='html')

    if command == "save":
        await _save_snapshot(context, account_id, name, event.client)
        await event.edit(format_success(f"Joriy profil {code(name)} nomi bilan saqlandi."), parse_mode='html')

    elif command == "load":
        snapshot = await context.db.fetchone("SELECT * FROM profile_snapshots WHERE account_id = ? AND snapshot_name = ?", (account_id, name))
        if not snapshot: return await event.edit(format_error(f"{code(name)} nomli zaxira topilmadi."), parse_mode='html')
        
        await event.client(UpdateProfileRequest(first_name=snapshot['first_name'], last_name=snapshot['last_name'], about=snapshot['bio']))
        if snapshot['photo_blob']:
            pfp_file = await event.client.upload_file(snapshot['photo_blob'])
            await event.client(UploadProfilePhotoRequest(file=pfp_file))
        await event.edit(format_success(f"{code(name)} nomli zaxira yuklandi."), parse_mode='html')

    elif command == "list":
        snapshots = await context.db.fetchall("SELECT snapshot_name, created_at FROM profile_snapshots WHERE account_id = ?", (account_id,))
        if not snapshots: return await event.edit("ℹ️ Saqlangan profil zaxiralari yo'q.", parse_mode='html')
        
        text = "\n".join(f"• {code(s['snapshot_name'])} ({s['created_at'][:10]})" for s in snapshots)
        await event.edit(f"<b>🗂️ Saqlangan profillar:</b>\n\n{text}", parse_mode='html')

    elif command == "del":
        rows = await context.db.execute("DELETE FROM profile_snapshots WHERE account_id = ? AND snapshot_name = ?", (account_id, name))
        msg = format_success(f"{code(name)} o'chirildi.") if rows > 0 else format_error(f"{code(name)} topilmadi.")
        await event.edit(msg, parse_mode='html')


@userbot_cmd(command="sessions", description="Aktiv seanslarni ko'rsatadi yoki tozalaydi.")
@admin_only
async def sessions_cmd(event: Message, context: AppContext):
    if not event.client or not event.text: return
    
    await event.edit("<i>🔄 Aktiv seanslar ro'yxati olinmoqda...</i>", parse_mode='html')
    try:
        auths = await event.client(GetAuthorizationsRequest())
        response = [bold("🔐 Aktiv seanslar:"), ""]
        for auth in auths.authorizations:
            response.append(
                f"<b>Device:</b> {code(auth.device_model)} ({auth.platform}){bold(' (Joriy)') if auth.current else ''}\n"
                f"<b>IP:</b> {code(auth.ip)} ({auth.country})\n"
                f"<b>Oxirgi faollik:</b> {code(auth.date_active.strftime('%Y-%m-%d %H:%M'))}\n"
                f"--------------------"
            )
        await event.edit("\n".join(response), parse_mode='html')
    except RPCError as e:
        await event.edit(format_error(html.escape(str(e))), parse_mode='html')


@userbot_cmd(command=["block", "unblock"], description="Foydalanuvchini bloklaydi yoki blokdan chiqaradi.")
@admin_only
async def block_unblock_user(event: Message, context: AppContext):
    if not event.client or not event.text: return
    command = event.text.split()[0].lstrip('.').lower()
    args = (event.text.split(maxsplit=1) + [""])[1].strip()

    target_user, error = await get_user(context, event, args)
    if error: return await event.edit(error, parse_mode='html')
    if not isinstance(target_user, types.User): return await event.edit(format_error("Foydalanuvchi topilmadi."), parse_mode='html')

    input_user = await event.client.get_input_entity(target_user)
    coro = event.client(UnblockRequest(id=input_user)) if command == "unblock" else event.client(BlockRequest(id=input_user))
    action_word = "blokdan chiqarildi" if command == "unblock" else "bloklandi"
    await _call_and_handle_errors(event, coro, format_success(f"{get_display_name(target_user)} muvaffaqiyatli {action_word}."))


@userbot_cmd(command="cleancontacts", description="O'chirilgan akkauntlarni kontaktlardan o'chiradi.")
@admin_only
async def clean_contacts(event: Message, context: AppContext):
    if not event.client or not event.text or not event.sender_id: return
    
    await event.edit("<i>🔄 Kontaktlar tekshirilmoqda...</i>", parse_mode='html')
    
    contacts_result = await event.client(functions.contacts.GetContactsRequest(hash=0))
    deleted_accounts = [c for c in contacts_result.users if isinstance(c, types.User) and c.deleted]
    
    if not deleted_accounts:
        return await event.edit("✅ Kontaktlaringiz toza, o'chirilgan akkauntlar topilmadi.", parse_mode='html')
    
    arg = (event.text.split(maxsplit=1) + [""])[1].strip()
    
    if arg.startswith("--confirm"):
        confirm_code = arg.split()[-1]
        confirm_key = f"confirm_cleancontacts:{event.sender_id}"
        if confirm_code == context.state.get(confirm_key):
            await context.state.delete(confirm_key)
            deleted_input_users = [await event.client.get_input_entity(u) for u in deleted_accounts]
            coro = event.client(DeleteContactsRequest(id=deleted_input_users))
            return await _call_and_handle_errors(event, coro, format_success(f"{len(deleted_input_users)} ta o'chirilgan akkaunt kontaktlardan tozalandi."))
        else:
            return await event.edit(format_error("Tasdiqlash kodi xato yoki vaqti o'tgan."), parse_mode='html')

    confirm_code = str(uuid.uuid4().hex[:6])
    confirm_key = f"confirm_cleancontacts:{event.sender_id}"
    await context.state.set(confirm_key, confirm_code, ttl_seconds=30)
    prompt = (f"⚠️ <b>DIQQAT!</b> Siz {len(deleted_accounts)} ta o'chirilgan akkauntni kontaktlaringizdan o'chirmoqchisiz.\n"
              f"✅ Davom etish uchun <b>30 soniya ichida</b> quyidagi buyruqni yuboring:\n"
              f"<code>.cleancontacts --confirm {confirm_code}</code>")
    await event.edit(prompt, parse_mode='html')


@userbot_cmd(command="blocklist", description="Bloklangan foydalanuvchilar ro'yxatini ko'rsatadi.")
@admin_only
async def blocklist_manager(event: Message, context: AppContext):
    if not event.client: return
    await event.edit("<code>🔄 Bloklanganlar ro'yxati olinmoqda...</code>", parse_mode='html')
    blocked = await event.client(GetBlockedRequest(offset=0, limit=100))
    if not hasattr(blocked, 'users') or not blocked.users:
        return await event.edit("ℹ️ Bloklangan foydalanuvchilar yo'q.", parse_mode='html')
    
    text = "\n".join(f"• {get_display_name(u)} ({code(u.id)})" for u in blocked.users)
    await event.edit(f"<b>🚫 Bloklanganlar ro'yxati:</b>\n\n{text}", parse_mode='html')


@userbot_cmd(command="2fa", description="Ikki faktorli autentifikatsiyani boshqaradi.")
@admin_only
async def two_fa_manager(event: Message, context: AppContext):
    """
    Foydalanish:
    .2fa enable <parol> [maslahat]
    .2fa disable <parol>
    """
    if not event.client or not event.text: return
    
    parts = event.text.split(maxsplit=2)
    if len(parts) < 3:
        return await event.edit(format_error("<b>Format xatosi.</b>\nFoydalanish: <code>.2fa enable|disable &lt;parol&gt; [maslahat]</code>"), parse_mode='html')

    command, password_or_arg = parts[1].lower(), parts[2]

    try:
        current_password = await event.client(functions.account.GetPasswordRequest())
        
        if command == 'enable':
            args = password_or_arg.split(maxsplit=1)
            new_password = args[0]
            hint = args[1] if len(args) > 1 else new_password
            
            await event.client(functions.account.UpdatePasswordSettingsRequest(
                password=current_password,
                new_settings=types.account.PasswordInputSettings(
                    new_password_hash=new_password.encode(),
                    hint=hint
                )
            ))
            await event.edit(format_success("2FA muvaffaqiyatli yoqildi."), parse_mode='html')

        elif command == 'disable':
            await event.client(functions.account.UpdatePasswordSettingsRequest(
                password=current_password,
                new_settings=types.account.PasswordInputSettings()
            ))
            await event.edit(format_success("2FA muvaffaqiyatli o'chirildi."), parse_mode='html')
        else:
            await event.edit(format_error("Noma'lum buyruq. `enable` yoki `disable` dan foydalaning."), parse_mode='html')
            
    except RPCError as e:
        await event.edit(format_error(f"Xatolik: {html.escape(str(e))}"), parse_mode='html')


@userbot_cmd(command="privacy", description="Maxfiylik sozlamalarini o'rnatadi.")
@admin_only
async def set_privacy_cmd(event: Message, context: AppContext):
    """
    Foydalanish: .privacy <qoida> <kimga> [istisnolar...]
    Qoidalar: last_seen, pfp, phone, status
    Kimga: everybody, contacts, nobody
    """
    if not event.client or not event.text: return
    
    parts = event.text.split()
    if len(parts) < 3:
        return await event.edit(format_error("<b>Format xatosi.</b>\nFoydalanish: <code>.privacy &lt;qoida&gt; &lt;kimga&gt; [istisnolar...]</code>"), parse_mode='html')

    key_str = parts[1].lower()
    value_str = parts[2].lower()
    exceptions_str = parts[3:]

    KEY_MAP = {
        "last_seen": InputPrivacyKeyStatusTimestamp(),
        "pfp": InputPrivacyKeyProfilePhoto(),
        "phone": InputPrivacyKeyPhoneNumber(),
        "status": InputPrivacyKeyForwards(),
    }
    VALUE_MAP = {
        "everybody": InputPrivacyValueAllowAll(),
        "contacts": InputPrivacyValueAllowContacts,
        "nobody": InputPrivacyValueDisallowAll(),
    }

    if key_str not in KEY_MAP or value_str not in VALUE_MAP:
        return await event.edit(format_error("Noto'g'ri qoida yoki qiymat."), parse_mode='html')

    key = KEY_MAP[key_str]
    rules: List[types.TypeInputPrivacyRule] = [VALUE_MAP[value_str]]
    
    if exceptions_str:
        except_users_input = []
        for user_id in exceptions_str:
            user, error = await get_user(context, event, user_id)
            if user:
                except_users_input.append(await event.client.get_input_entity(user))
        
        if except_users_input:
            if isinstance(rules[0], InputPrivacyValueAllowAll):
                rules.append(InputPrivacyValueDisallowUsers(users=except_users_input))
            elif isinstance(rules[0], InputPrivacyValueDisallowAll):
                rules.append(InputPrivacyValueAllowUsers(users=except_users_input))

    coro = event.client(SetPrivacyRequest(key=key, rules=rules))
    await _call_and_handle_errors(event, coro, format_success(f"'{key_str}' uchun maxfiylik sozlamalari o'rnatildi."))