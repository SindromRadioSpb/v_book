import os

from google.cloud import translate_v3


def main() -> None:
    credentials = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not credentials:
        raise RuntimeError(
            "Set GOOGLE_APPLICATION_CREDENTIALS to the path of your"
            " Google Cloud service account JSON key file.\n"
            "  Example: $env:GOOGLE_APPLICATION_CREDENTIALS = 'C:\\keys\\sa.json'"
        )

    project_id = os.environ.get("GCP_PROJECT_ID")
    if not project_id:
        raise RuntimeError(
            "Set GCP_PROJECT_ID to your Google Cloud project ID.\n"
            "  Example: $env:GCP_PROJECT_ID = 'your-project-id'"
        )

    location = "global"
    parent = f"projects/{project_id}/locations/{location}"

    client = translate_v3.TranslationServiceClient()

    response = client.translate_text(
        request={
            "parent": parent,
            "contents": ["Привет, мир!"],
            "target_language_code": "en",
            "source_language_code": "ru",
            "mime_type": "text/plain",
        }
    )

    print("OK:", response.translations[0].translated_text)


if __name__ == "__main__":
    main()
