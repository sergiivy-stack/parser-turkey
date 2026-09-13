import asyncio
from telethon import TelegramClient

API_ID = 37120678
API_HASH = "3a555ff9e42920968b08cb85083b965b"

client = TelegramClient("turkey_realestate_parser", API_ID, API_HASH)


async def main():
    await client.start()
    print("\n📋 Список твоих диалогов и их РЕАЛЬНЫЕ chat_id (как их видит Telethon):\n")
    async for dialog in client.iter_dialogs():
        print(f"{dialog.id:>16}  |  {dialog.name}")


if __name__ == "__main__":
    asyncio.run(main())
