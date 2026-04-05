from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    """应用配置，从环境变量加载，前缀为 SPM_"""

    app_name: str = "Steam Price Monitor"
    database_url: str = Field(
        default_factory=lambda: f"sqlite:///{(BASE_DIR / 'steam_monitor.db').as_posix()}",
        description="SQLAlchemy 数据库连接字符串",
    )
    scheduler_enabled: bool = Field(default=True, description="是否启用定时调度器")
    timezone: str = Field(default="Asia/Shanghai", description="时区设置")
    default_currency: str = Field(default="CNY", description="默认货币代码")
    refresh_interval_minutes: int = Field(
        default=180, gt=0, description="定时刷新间隔（分钟）"
    )
    full_sync_hour: int = Field(default=6, ge=0, le=23, description="每天全量同步的小时数")
    alert_cooldown_hours: int = Field(
        default=24, gt=0, description="相同告警的冷却期（小时）"
    )
    steam_country_code: str = Field(
        default="cn", description="Steam API 国家代码（两字母小写）"
    )
    steam_language: str = Field(
        default="schinese", description="Steam API 语言代码"
    )
    request_timeout_seconds: int = Field(
        default=10, gt=0, description="HTTP 请求超时时间（秒）"
    )
    xiaoheihe_enabled: bool = Field(default=False, description="是否启用小黑盒数据源")
    xiaoheihe_base_url: str = Field(default="", description="小黑盒 API 基础 URL")
    smtp_host: str = Field(default="", description="SMTP 服务器地址")
    smtp_port: int = Field(default=587, ge=1, le=65535, description="SMTP 服务器端口")
    smtp_username: str = Field(default="", description="SMTP 用户名")
    smtp_password: str = Field(default="", description="SMTP 密码")
    smtp_sender: str = Field(default="", description="邮件发送者地址")
    notification_email: str = Field(default="", description="接收告警的邮箱地址")
    smtp_use_tls: bool = Field(default=True, description="SMTP 是否使用 TLS")
    smtp_use_ssl: bool = Field(default=False, description="SMTP 是否直接使用 SSL")

    model_config = SettingsConfigDict(
        env_prefix="SPM_",
        env_file=".env",
        case_sensitive=False,
    )

    @field_validator("steam_country_code")
    @classmethod
    def validate_country_code(cls, v: str) -> str:
        """验证国家代码格式"""
        if not v:
            return v
        if not re.match(r"^[a-z]{2}$", v):
            raise ValueError("国家代码必须是两个小写字母，例如 'cn'、'us'")
        return v

    @field_validator("steam_language")
    @classmethod
    def validate_language(cls, v: str) -> str:
        """验证 Steam 支持的语言"""
        if not v:
            return v
        valid_languages = {
            "english",
            "schinese",
            "tchinese",
            "japanese",
            "korean",
            "spanish",
            "german",
            "french",
            "italian",
            "portuguese",
            "russian",
        }
        if v.lower() not in valid_languages:
            raise ValueError(
                f"不支持的语言: {v}。支持的语言: {', '.join(sorted(valid_languages))}"
            )
        return v

    @field_validator("refresh_interval_minutes")
    @classmethod
    def validate_refresh_interval(cls, v: int) -> int:
        """验证刷新间隔"""
        if v < 1:
            raise ValueError("刷新间隔必须至少 1 分钟")
        if v > 1440:  # 24小时
            raise ValueError("刷新间隔不能超过 24 小时（1440 分钟）")
        return v

    @property
    def templates_dir(self) -> Path:
        return BASE_DIR / "steam_price_monitor" / "templates"

    @property
    def static_dir(self) -> Path:
        return BASE_DIR / "steam_price_monitor" / "static"

    @property
    def logs_dir(self) -> Path:
        return BASE_DIR / "logs"

    @classmethod
    def from_env(cls) -> "Settings":
        """从环境变量创建设置实例"""
        return cls()
