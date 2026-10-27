import re
from datetime import datetime

def sanitize_filename(filename: str) -> str:
    """
    Sanitizes a string to ensure it is safe for Windows and Unix filesystems.
    Removes invalid characters: < > : " / \\ | ? * and strips leading/trailing spaces/dots.
    """
    if not filename:
        return ""
    from smart.rules import safe_filename
    return safe_filename(filename)

def get_media_filename(message, prefix_date=None, default_ext=None, channel=None, prefix_channel=None, target_media=None, sub_index=None) -> str:
    """
    Generates a clean, consistent filename for any Telegram message media.
    If prefix_date is True (or enabled in config), prepends 'YYYY-MM-DD_' based on message.date.
    If prefix_channel is True (or enabled in config), prepends '@channel_' or 'channel_title_'.
    Supports Telegram Stars Paid Media (MessageMediaPaidMedia) and multi-part media albums.
    
    Examples:
    - Photo with date: '2026-01-01_Photo_105.jpg'
    - With channel handle: '@channel_2026-01-01_Photo_105.jpg'
    - Video with original name: '2026-01-01_my_clip.mp4'
    - Star paid media album item: '@channel_2026-01-01_Photo_105_1.jpg'
    """
    if prefix_date is None or prefix_channel is None:
        try:
            from ui.views.settings_view import load_config
            cfg = load_config()
            if prefix_date is None:
                prefix_date = cfg.get("prefix_file_date", True)
            if prefix_channel is None:
                prefix_channel = cfg.get("prefix_channel_handle", False)
        except Exception:
            if prefix_date is None:
                prefix_date = True
            if prefix_channel is None:
                prefix_channel = False

    msg_id = getattr(message, 'id', 0)
    
    # 0. Handle Star Paid Media if target_media is not provided
    media_obj = target_media
    if media_obj is None:
        msg_media = getattr(message, 'media', None)
        try:
            from telethon.tl.types import MessageMediaPaidMedia, MessageExtendedMedia, MessageExtendedMediaPreview
            if isinstance(msg_media, MessageMediaPaidMedia) and getattr(msg_media, 'extended_media', None):
                # Inspect extended media items
                first_item = msg_media.extended_media[0]
                if isinstance(first_item, MessageExtendedMedia):
                    media_obj = first_item.media
                elif isinstance(first_item, MessageExtendedMediaPreview):
                    media_obj = first_item
        except Exception:
            pass

    # 1. Resolve Extension
    ext = ""
    if getattr(message, 'file', None) and getattr(message.file, 'ext', None):
        ext = message.file.ext or ""
    if not ext and default_ext:
        ext = default_ext

    # 2. Check Media Types
    is_photo = bool(getattr(message, 'photo', None))
    mime = ""
    if getattr(message, 'document', None):
        mime = getattr(message.document, 'mime_type', '') or ""
    elif getattr(message, 'file', None):
        mime = getattr(message.file, 'mime_type', '') or ""

    # Check media_obj if target_media was provided or unpacked from paid media
    if media_obj is not None:
        try:
            from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument, MessageExtendedMediaPreview
            if isinstance(media_obj, MessageMediaPhoto) or hasattr(media_obj, 'photo'):
                is_photo = True
                if not ext:
                    ext = ".jpg"
            elif isinstance(media_obj, MessageMediaDocument) or hasattr(media_obj, 'document'):
                doc = getattr(media_obj, 'document', media_obj)
                mime = getattr(doc, 'mime_type', '') or mime
            elif isinstance(media_obj, MessageExtendedMediaPreview):
                if getattr(media_obj, 'video_duration', None):
                    mime = "video/mp4"
                    if not ext:
                        ext = ".mp4"
                else:
                    is_photo = True
                    if not ext:
                        ext = ".jpg"
        except Exception:
            pass

    is_video = bool(getattr(message, 'video', None) or (mime and mime.startswith('video/')))
    is_audio = bool(getattr(message, 'audio', None) or getattr(message, 'voice', None) or (mime and mime.startswith('audio/')))

    # 3. Check for explicitly named file in Telegram metadata
    orig_name = None
    if getattr(message, 'file', None) and getattr(message.file, 'name', None):
        orig_name = message.file.name
    else:
        doc_obj = getattr(message, 'document', None)
        if media_obj is not None and (hasattr(media_obj, 'document') or hasattr(media_obj, 'attributes')):
            doc_obj = getattr(media_obj, 'document', media_obj)

        if doc_obj and getattr(doc_obj, 'attributes', None):
            try:
                from telethon.tl.types import DocumentAttributeFilename
                for attr in doc_obj.attributes:
                    if isinstance(attr, DocumentAttributeFilename) and getattr(attr, 'file_name', None):
                        orig_name = attr.file_name
                        break
            except Exception:
                pass

    # 4. Determine Base Filename
    suffix = f"_{sub_index}" if sub_index is not None else ""

    if orig_name:
        if sub_index is not None:
            base, ext_orig = re.sub(r'\.[^.]+$', '', orig_name), (re.search(r'\.[^.]+$', orig_name).group(0) if re.search(r'\.[^.]+$', orig_name) else "")
            base_name = f"{base}{suffix}{ext_orig}"
        else:
            base_name = orig_name
    elif is_photo:
        base_name = f"Photo_{msg_id}{suffix}{ext if ext else '.jpg'}"
    elif is_video:
        base_name = f"Video_{msg_id}{suffix}{ext if ext else '.mp4'}"
    elif is_audio:
        base_name = f"Audio_{msg_id}{suffix}{ext if ext else '.mp3'}"
    elif mime == 'application/pdf':
        base_name = f"Document_{msg_id}{suffix}{ext if ext else '.pdf'}"
    elif mime in ['application/zip', 'application/x-rar-compressed', 'application/x-7z-compressed']:
        base_name = f"Document_{msg_id}{suffix}{ext if ext else '.zip'}"
    else:
        base_name = f"Document_{msg_id}{suffix}{ext}"

    base_name = sanitize_filename(base_name)

    # 5. Extract Publication Date
    date_prefix = ""
    if prefix_date:
        msg_date = getattr(message, 'date', None)
        if msg_date:
            if isinstance(msg_date, str):
                try:
                    msg_date = datetime.fromisoformat(msg_date)
                except Exception:
                    if len(msg_date) >= 10 and msg_date[4] == '-' and msg_date[7] == '-':
                        date_prefix = msg_date[:10]
            if hasattr(msg_date, 'strftime'):
                date_prefix = msg_date.strftime("%Y-%m-%d")

    # 6. Prepend Date Prefix if available and not already present
    if date_prefix and not base_name.startswith(date_prefix):
        base_name = f"{date_prefix}_{base_name}"

    # 7. Extract and Prepend Channel Handle / Title if requested
    if prefix_channel:
        ch_obj = channel or getattr(message, 'chat', None) or getattr(message, '_chat', None)
        ch_handle = None
        if ch_obj:
            username = getattr(ch_obj, 'username', None)
            title = getattr(ch_obj, 'title', None)
            if username:
                ch_handle = f"@{username}"
            elif title:
                ch_handle = sanitize_filename(title)
        
        if ch_handle and not base_name.startswith(ch_handle):
            base_name = f"{ch_handle}_{base_name}"

    return base_name
