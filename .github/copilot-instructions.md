# Copilot Instructions for VPN Bot

This document provides guidance for AI coding agents working on the VPN Bot project. It outlines the architecture, workflows, and conventions specific to this codebase to ensure productive contributions.

## Project Overview

VPN Bot is a Telegram bot for managing VPN subscriptions via the XUI panel. The project is structured as follows:

- **`main.py`**: Entry point for the bot. Initializes the bot, registers handlers, sets up the webhook, and starts the server.
- **`config.py`**: Loads environment variables from `.env` and validates required parameters.
- **`database.py`**: Handles SQLite database operations, including user management.
- **`xui_api.py`**: Provides API functions for interacting with the XUI panel.
- **`handlers.py`**: Contains Telegram bot command and button handlers.

## Key Workflows

### Installation
1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Create a `.env` file based on `.env.example` and populate it with your credentials.

### Running the Bot
Start the bot with:
```bash
python main.py
```

### Database Initialization
Ensure the SQLite database is initialized by calling `init_db()` from `database.py`.

## Project-Specific Conventions

- **Environment Variables**: All sensitive data (e.g., API tokens, credentials) must be stored in the `.env` file. Never commit `.env` to version control.
- **Handler Registration**: Add new Telegram bot commands or buttons in `handlers.py`. Ensure they are registered in `main.py`.
- **XUI API Integration**: Use `xui_api.py` for all interactions with the XUI panel. Avoid duplicating API logic elsewhere.

## Integration Points

- **Telegram API**: The bot communicates with Telegram servers using the `python-telegram-bot` library.
- **XUI Panel**: The bot interacts with the XUI panel for VPN subscription management. Key functions include:
  - `get_xui_cookie()`: Authentication
  - `get_users()`: Fetching user data
  - `create_trial_inbound()`: Creating trial subscriptions

## Examples

### Adding a New Command
To add a new `/example` command:
1. Define the handler in `handlers.py`:
   ```python
   def example(update, context):
       update.message.reply_text("This is an example command.")
   ```
2. Register the handler in `main.py`:
   ```python
   dispatcher.add_handler(CommandHandler("example", example))
   ```

### Adding a New XUI API Function
To add a new API function in `xui_api.py`:
1. Define the function:
   ```python
   def new_function():
       # API logic here
   ```
2. Document the function in the `README.md` under the `xui_api.py` section.

## Security Notes

- Ensure `.env` is never committed to version control.
- Validate all user inputs to prevent injection attacks.

## Additional Resources

- Refer to `README.md` for detailed setup instructions.
- Use `specification.md` for understanding project requirements and goals.