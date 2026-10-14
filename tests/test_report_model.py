"""models.py 的 JSON 序列化和反序列化测试。"""

from __future__ import annotations

import datetime as dt
import json

from comfyui_time_machine.models import (
    ComfyUIInstallation,
    ConfigFileInfo,
    CustomNodeInfo,
    DetectionStatus,
    GitInfo,
    InstallationType,
    ScanReport,
    ScanWarning,
)


def test_minimal_report_roundtrip():
    """最小 ScanReport 能正确序列化和反序列化。"""
    report = ScanReport(schema_version="0.1", app_version="0.1.0")
    text = report.to_json()
    back = ScanReport.from_json(text)
    assert report.schema_version == back.schema_version
    assert report.app_version == back.app_version
    assert isinstance(back, ScanReport)


def test_full_report_roundtrip():
    """包含嵌套 dataclass、枚举、datetime、Path 的完整报告。"""
    now = dt.datetime.now()
    report = ScanReport(
        schema_version="0.1",
        app_version="0.1.0",
        scan_started_at=now,
        scan_completed_at=now,
        installation=ComfyUIInstallation(
            type=InstallationType.PORTABLE_WINDOWS,
            detected_at=now,
            status=DetectionStatus.DETECTED,
            git=GitInfo(
                is_git_repo=True,
                commit="abc123",
                branch="main",
                has_local_changes=False,
                status=DetectionStatus.DETECTED,
            ),
        ),
        custom_nodes=[
            CustomNodeInfo(
                name="ComfyUI-Manager",
                git=GitInfo(is_git_repo=True, commit="def456", status=DetectionStatus.DETECTED),
                has_requirements_txt=True,
            ),
            CustomNodeInfo(
                name="SomeNodes",
                git=GitInfo(status=DetectionStatus.NOT_PRESENT),
            ),
        ],
        config_files=[
            ConfigFileInfo(path="C:/foo/bar.yaml", exists=True, contains_secrets=True, sensitive_keys_detected=["api_key"]),
        ],
        warnings=[
            ScanWarning(level="warning", category="test", message="一条警告"),
        ],
    )

    text = report.to_json()
    data = json.loads(text)

    # 基本字段
    assert data["schema_version"] == "0.1"
    assert data["app_version"] == "0.1.0"
    assert len(data["custom_nodes"]) == 2
    assert data["warnings"][0]["level"] == "warning"
    # 枚举序列化成值字符串
    assert data["installation"]["type"] == "portable_windows"
    assert data["installation"]["status"] == "detected"
    # datetime → ISO 字符串
    assert "T" in data["scan_started_at"]

    # 反序列化
    back = ScanReport.from_json(text)
    assert back.scan_started_at == report.scan_started_at
    assert back.installation.type == InstallationType.PORTABLE_WINDOWS
    assert back.installation.git.commit == "abc123"
    assert len(back.custom_nodes) == 2
    assert back.custom_nodes[0].git.commit == "def456"
    assert back.config_files[0].contains_secrets is True


def test_report_keys_do_not_contain_secrets_placeholder():
    """模型本身不包含任何秘密值字段。"""
    git = GitInfo()
    assert not hasattr(git, "token")
    assert not hasattr(git, "password")

    cfg = ConfigFileInfo(sensitive_keys_detected=["api_key"])
    # sensitive_keys_detected 只记录键名，不记录值
    assert cfg.sensitive_keys_detected == ["api_key"]
