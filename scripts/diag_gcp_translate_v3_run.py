import os
from google.cloud import translate_v3


def main() -> None:
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = (
        r"J:\Project_Vibe\V_book -info files\api_key_Google_translait\hdle-translate-sa.json"
    )

    project_id = "gen-lang-client-0212091660"
    location = "global"

    parent = f"projects/{project_id}/locations/{location}"

    client = translate_v3.TranslationServiceClient()

    response = client.translate_text(
        request={
            "parent": parent,
            "contents": ["ривет, мир!"],
            "target_language_code": "en",
            "source_language_code": "ru",
            "mime_type": "text/plain",
        }
    )

    print("OK:", response.translations[0].translated_text)


if __name__ == "__main__":
    main()
