from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from aivenv.config import Settings, load_settings


def clear_config_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "OPENAI_API_KEY",
        "AIVENV_OPENAI_API_KEY",
        "NGROK_AUTHTOKEN",
        "AIVENV_NGROK_AUTHTOKEN",
        "AIVENV_HOST",
        "AIVENV_PORT",
        "PORT",
        "AIVENV_LOG_HOST",
        "AIVENV_LOG_PORT",
        "LOG_PORT",
        "AIVENV_OPENAI_MODEL",
        "OPENAI_MODEL",
        "AIVENV_CONTAINER_IMAGE",
        "CONTAINER_IMAGE",
        "AIVENV_CPU_LIMIT",
        "CPU_LIMIT",
        "AIVENV_MEMORY_LIMIT",
        "MEMORY_LIMIT",
        "AIVENV_CLEANUP_ON_EXIT",
        "CLEANUP_ON_EXIT",
        "AIVENV_EXECUTION_TIMEOUT_SECONDS",
        "EXICUTION_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(key, raising=False)


def set_required_env(!��������э����ѕ�й5�����A�э������9����(������������э��͕ѕ�ؠ�=A9%}A%}-d����ͬ�ѕ�Ј�(������������э��͕ѕ�ؠ�9I=-}UQ!Q=-8������ɽ��ѕ�Ј�(()����ѕ��}�����}����ձ��}ݥѡ}ɕ�եɕ�}͕�ɕ�̡��������э����ѕ�й5�����A�э������9����(���������}������}��ؠmonkeypatch)
    set_required_env(monkeypatch)

    settings = Settings()

    assert isinstance(settings.openai_api_key, SecretStr)
    assert isinstance(settings.ngrok_authtoken, SecretStr)
    assert settings.openai_api_key_value == "sk-test"
    assert settings.ngrok_authtoken_value == "ngrok-test"
    assert settings.port == 8080
    assert settings.log_port == 8081
    assert settings.openai_model == "gpt-4o"
    assert settings.container_image == "python:3.11-slim"
    assert settings.cpu_limit == 1.0
    assert settings.memory_limit == "512m"
    assert settings.cleanup_on_exit is True
    assert settings.log_server_url == "http://127.0.0.1:8081"


def test_cli_overrides_take_precedence_over_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_config_env(monkeypatch)
    set_required_env([ۚ�^\]�
B�[ۚ�^\]���][���RU�S���ԕ���B���][���H�Y��][������[�ZW�\W��^H�����X�H����ܛ���]]��[�����ܛ��X�H���ܝ��L�����ܝ��LK���[�ZW�[�[����M�H����۝Z[�\��[XY�H���]ێ�ˌL�\�[H����W�[Z]�����Y[[ܞW�[Z]���Yȋ���X[�\�ۗ�^]���[�K��^X�][ۗ�[Y[�]��X�ۙȎ���������ۙK�B�
B��\��\��][��˛�[�ZW�\W��^Wݘ[YHOH���X�H��\��\��][��˛�ܛ���]]��[�ݘ[YHOH��ܛ��X�H��\��\��][��˜ܝOHL�\��\��][��˛���ܝOHLB�\��\��][��˛�[�ZW�[�[OH��M�H��\��\��][��˘�۝Z[�\��[XY�HOH�]ێ�ˌL�\�[H��\��\��][��˘�W�[Z]OH���\��\��][��˛Y[[ܞW�[Z]OH�YȂ�\��\��][��˘�X[�\�ۗ�^]\��[�B�\��\��][��˙^X�][ۗ�[Y[�]��X�ۙ�OH��\��\��][��˚��OH�L�ˌ��H����Y�\��Z\��[��ܙ\]Z\�Y�ܙY[�X[�ܘZ\�Wݘ[Y][ۗ�\��܊[ۚ�^\]��]\��[ۚ�^T]�
HO��ۙN���X\���ۙ�Y��[��[ۚ�^\]�
B���]]\���Z\�\��[Y][ۑ\��܊H\�^��[��΂��][���
B��Y\��Y�HH��^��[��˝�[YJB�\��\���S�RW�TW��VH�[�Y\��Y�B�\��\���ԓ���UU��S��[�Y\��Y�B���Y�\��[��[Y�ܝ��[�ܙ\��\��W�[Z]��\�WܙZ�X�Y
[ۚ�^\]��]\��[ۚ�^T]�
HO��ۙN���X\���ۙ�Y��[��[ۚ�^\]�
B��]ܙ\]Z\�Y�[��[ۚ�^\]�
B���]]\���Z\�\��[Y][ۑ\��܊N���][���ܝM�
B���]]\���Z\�\��[Y][ۑ\��܊N���][����W�[Z]L
B���]]\���Z\�\��[Y][ۑ\��܊N���][���Y[[ܞW�[Z]H�LL��B���Y�\���Xܙ]ݘ[Y\��\�WܙYX�Y�[�ܙ\�[ۚ�^\]��]\��[ۚ�^T]�
HO��ۙN���X\���ۙ�Y��[��[ۚ�^\]�
B��]ܙ\]Z\�Y�[��[ۚ�^\]�
B���[�\�YH�\��][���
JB��\��\����]\����[��[�\�Y�\��\���ܛ��]\����[��[�\�Y�\��\������������[��[�\�Y