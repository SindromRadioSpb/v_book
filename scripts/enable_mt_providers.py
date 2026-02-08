"""Enable MT providers automatically.

This script configures MT provider settings:
- Enables master switch (mt/providers/enabled = True)
- Configures provider chain with local_nllb first
- Enables local_nllb provider
"""
import json
from PyQt6.QtCore import QSettings


def enable_mt_providers():
    """Enable MT providers with default configuration."""
    settings = QSettings(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        "HDLE_Premium",
        "HDLE_Premium"
    )

    print("Configuring MT provider settings...")
    print(f"Settings file: {settings.fileName()}")

    # 1. Enable master switch
    settings.setValue("mt/providers/enabled", True)
    print("\n[OK] Enabled master switch (mt/providers/enabled = True)")

    # 2. Configure provider chain (local_nllb first for offline use)
    chain = ["local_nllb", "deepl", "microsoft", "libretranslate", "local_seamless"]
    chain_json = json.dumps(chain)
    settings.setValue("mt/providers/chain", chain_json)
    print(f"[OK] Configured provider chain: {chain}")

    # 3. Enable individual providers
    providers_config = {
        "local_nllb": {"enabled": True, "rate_limit": 9999},
        "deepl": {"enabled": False, "rate_limit": 60},  # Disabled by default (requires API key)
        "microsoft": {"enabled": False, "rate_limit": 60},  # Disabled by default (requires API key)
        "libretranslate": {"enabled": False, "rate_limit": 60},  # Disabled by default
        "local_seamless": {"enabled": False, "rate_limit": 9999},  # Disabled by default (model not installed)
    }

    print("\n[OK] Configured individual providers:")
    for provider_id, config in providers_config.items():
        enabled_key = f"mt/providers/{provider_id}/enabled"
        rate_limit_key = f"mt/providers/{provider_id}/rate_limit"

        settings.setValue(enabled_key, config["enabled"])
        settings.setValue(rate_limit_key, config["rate_limit"])

        status = "ENABLED" if config["enabled"] else "DISABLED"
        print(f"  - {provider_id}: {status} (rate_limit={config['rate_limit']})")

    # Sync to disk
    settings.sync()
    print("\n[OK] Settings saved successfully!")
    print("\nYou can now use batch translate with MT providers.")
    print("To customize settings, open the provider settings dialog in the app.")


if __name__ == "__main__":
    enable_mt_providers()
