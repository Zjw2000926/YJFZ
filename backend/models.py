from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, Float, DateTime as SAType, ForeignKey, JSON, Index
from sqlalchemy.types import TypeDecorator
from sqlalchemy.orm import relationship
from database import Base


class UtcDateTime(TypeDecorator):
    """确保 SQLite 读写时 UTC 时区信息不丢失，Pydantic 序列化时带 Z/+00:00 后缀"""
    impl = SAType
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            return value.replace(tzinfo=timezone.utc)
        return value


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(10), nullable=False, default="student")  # student / teacher
    display_name = Column(String(50), nullable=False)
    student_id = Column(String(30), nullable=True)
    created_at = Column(UtcDateTime, default=lambda: datetime.now(timezone.utc))

    training_records = relationship("TrainingRecord", back_populates="user")


class Case(Base):
    __tablename__ = "cases"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    case_data = Column(JSON, nullable=False)  # 完整病例数据
    created_at = Column(UtcDateTime, default=lambda: datetime.now(timezone.utc))


class TrainingRecord(Base):
    __tablename__ = "training_records"
    __table_args__ = (
        Index("ix_tr_user_status", "user_id", "status"),
        Index("ix_tr_status", "status"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False)
    status = Column(String(20), nullable=False, default="in_progress")  # in_progress / completed
    scoring_status = Column(String(20), nullable=True)  # null / pending / processing / completed / failed
    scoring_error = Column(Text, nullable=True)  # 评分失败时的错误信息
    start_time = Column(UtcDateTime, default=lambda: datetime.now(timezone.utc))
    end_time = Column(UtcDateTime, nullable=True)

    user = relationship("User", back_populates="training_records")
    case = relationship("Case")
    messages = relationship("Message", back_populates="record", order_by="Message.created_at")
    score = relationship("Score", back_populates="record", uselist=False)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_msg_record_created", "record_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    record_id = Column(Integer, ForeignKey("training_records.id"), nullable=False)
    role = Column(String(10), nullable=False)  # student / patient
    content = Column(Text, nullable=False)
    created_at = Column(UtcDateTime, default=lambda: datetime.now(timezone.utc))

    record = relationship("TrainingRecord", back_populates="messages")


class Score(Base):
    __tablename__ = "scores"

    id = Column(Integer, primary_key=True, index=True)
    record_id = Column(Integer, ForeignKey("training_records.id"), unique=True, nullable=False)
    total_score = Column(Float, nullable=False)
    detail_scores = Column(JSON, nullable=True)
    strengths = Column(JSON, nullable=True)
    weaknesses = Column(JSON, nullable=True)
    missed_content = Column(JSON, nullable=True)
    suggestions = Column(Text, nullable=True)
    # 评分标准版本追踪
    rubric_version = Column(String(40), nullable=True)
    model_name = Column(String(80), nullable=True)
    prompt_version = Column(Integer, nullable=True, default=1)
    score_scale = Column(Integer, nullable=True, default=100)
    # 教师复核
    review_status = Column(String(20), nullable=True)  # null / reviewed
    reviewed_by = Column(Integer, nullable=True)
    reviewed_at = Column(UtcDateTime, nullable=True)
    review_detail_scores = Column(JSON, nullable=True)
    review_comment = Column(Text, nullable=True)
    created_at = Column(UtcDateTime, default=lambda: datetime.now(timezone.utc))

    record = relationship("TrainingRecord", back_populates="score")


class Note(Base):
    __tablename__ = "notes"

    id = Column(Integer, primary_key=True, index=True)
    record_id = Column(Integer, ForeignKey("training_records.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(UtcDateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(UtcDateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class LLMCallLog(Base):
    """记录每次 LLM 调用的元数据，用于成本监控和稳定性分析"""
    __tablename__ = "llm_call_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    record_id = Column(Integer, ForeignKey("training_records.id"), nullable=True, index=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=True, index=True)
    purpose = Column(String(40), nullable=False, index=True)  # patient_chat / scoring / qa / summary / other
    provider = Column(String(40), nullable=False, default="deepseek")
    model = Column(String(80), nullable=False)
    temperature = Column(Float, nullable=True)
    max_tokens = Column(Integer, nullable=True)
    prompt_tokens = Column(Integer, nullable=True)
    completion_tokens = Column(Integer, nullable=True)
    total_tokens = Column(Integer, nullable=True)
    token_estimated = Column(Integer, nullable=False, default=1)  # 0=真实usage, 1=估算
    estimated_cost = Column(Float, nullable=True)
    cost_currency = Column(String(10), nullable=True, default="CNY")
    latency_ms = Column(Integer, nullable=True, index=True)
    status = Column(String(20), nullable=False, index=True)  # success / failed / timeout / rate_limited / auth_error
    error_type = Column(String(80), nullable=True, index=True)
    error_message = Column(Text, nullable=True)
    request_chars = Column(Integer, nullable=True)
    response_chars = Column(Integer, nullable=True)
    meta = Column(JSON, nullable=True)
    created_at = Column(UtcDateTime, default=lambda: datetime.now(timezone.utc), index=True)


# ── P0-1: 预检分诊表 ──
class TriageCase(Base):
    __tablename__ = "triage_cases"
    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(String(80), unique=True, nullable=False, index=True)
    stage = Column(String(20), nullable=False, default="V1")
    title = Column(String(200))
    display_name = Column(String(200))
    difficulty = Column(Integer, default=1)
    category = Column(String(80))
    case_data = Column(JSON, nullable=False)
    rubric_id = Column(String(40))
    is_active = Column(Integer, default=1)
    expert_review_status = Column(String(20), default="draft")
    created_at = Column(UtcDateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(UtcDateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class TriageTrainingRecord(Base):
    __tablename__ = "triage_training_records"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    case_external_id = Column(String(80))
    case_id = Column(Integer, nullable=True)
    mode = Column(String(20), default="practice")
    task_id = Column(String(40), nullable=True)
    cohort_id = Column(String(40), nullable=True)
    status = Column(String(20), default="in_progress")
    variant_id = Column(String(40), default="default")
    total_score = Column(Float, nullable=True)
    pass_status = Column(String(20), nullable=True)
    severe_error_triggered = Column(Integer, default=0)
    severe_error_codes = Column(JSON, nullable=True)
    final_level_selected = Column(String(10))
    final_zone_selected = Column(String(20))
    final_disposition = Column(JSON, nullable=True)
    disclosed_slots = Column(JSON, nullable=True)
    measured_vitals = Column(JSON, nullable=True)
    intent_events = Column(JSON, nullable=True)
    score_detail = Column(JSON, nullable=True)
    rule_result = Column(JSON, nullable=True)
    standard_answer = Column(JSON, nullable=True)
    timeline_report = Column(JSON, nullable=True)
    feedback = Column(JSON, nullable=True)
    teacher_review = Column(JSON, nullable=True)
    scoring_version = Column(String(20))
    rubric_version = Column(String(40))
    rule_set_version = Column(String(40))
    app_version = Column(String(20))
    process_data = Column(JSON, nullable=True)
    started_at = Column(UtcDateTime, default=lambda: datetime.now(timezone.utc))
    submitted_at = Column(UtcDateTime, nullable=True)
    created_at = Column(UtcDateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(UtcDateTime, default=lambda: datetime.now(timezone.utc))

class TriageMessage(Base):
    __tablename__ = "triage_messages"
    id = Column(Integer, primary_key=True, index=True)
    record_id = Column(Integer, ForeignKey("triage_training_records.id"), nullable=False, index=True)
    role = Column(String(20))
    content = Column(Text)
    matched_intent = Column(String(80), nullable=True)
    disclosed_slots = Column(JSON, nullable=True)
    created_at = Column(UtcDateTime, default=lambda: datetime.now(timezone.utc))

class TriageAction(Base):
    __tablename__ = "triage_actions"
    id = Column(Integer, primary_key=True, index=True)
    record_id = Column(Integer, ForeignKey("triage_training_records.id"), nullable=False, index=True)
    action_type = Column(String(40))
    payload = Column(JSON, nullable=True)
    created_at = Column(UtcDateTime, default=lambda: datetime.now(timezone.utc))

class TriageCohort(Base):
    __tablename__ = "triage_cohorts"
    id = Column(String(40), primary_key=True)
    name = Column(String(200))
    description = Column(Text)
    created_by = Column(Integer)
    members = Column(JSON, nullable=True)
    created_at = Column(UtcDateTime, default=lambda: datetime.now(timezone.utc))

class TriageTask(Base):
    __tablename__ = "triage_tasks"
    id = Column(String(40), primary_key=True)
    title = Column(String(200))
    cohort_id = Column(String(40))
    mode = Column(String(20), default="practice")
    case_external_ids = Column(JSON, nullable=True)
    time_limit_minutes = Column(Integer, default=8)
    allow_hints = Column(Integer, default=1)
    allow_retry = Column(Integer, default=1)
    show_feedback_immediately = Column(Integer, default=1)
    status = Column(String(20), default="published")
    assignments = Column(JSON, nullable=True)
    created_by = Column(Integer)
    created_at = Column(UtcDateTime, default=lambda: datetime.now(timezone.utc))

class TriageCaseReview(Base):
    __tablename__ = "triage_case_reviews"
    id = Column(String(40), primary_key=True)
    case_id = Column(String(80))
    reviewer_id = Column(Integer)
    status = Column(String(20))
    comment = Column(Text)
    reviewed_at = Column(UtcDateTime, default=lambda: datetime.now(timezone.utc))

class TriageScenario(Base):
    __tablename__ = "triage_scenarios"
    id = Column(String(40), primary_key=True)
    external_id = Column(String(80))
    title = Column(String(200))
    scenario_type = Column(String(40))
    difficulty = Column(Integer, default=1)
    description = Column(Text)
    resource_context = Column(JSON, nullable=True)
    standard_strategy = Column(JSON, nullable=True)
    expert_review_status = Column(String(20), default="pending")
    created_at = Column(UtcDateTime, default=lambda: datetime.now(timezone.utc))

class TriageLearningPath(Base):
    __tablename__ = "triage_learning_paths"
    id = Column(String(40), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    profile_snapshot = Column(JSON, nullable=True)
    recommendations = Column(JSON, nullable=True)
    status = Column(String(20), default="active")
    generated_at = Column(UtcDateTime, default=lambda: datetime.now(timezone.utc))

class TriageAiEvent(Base):
    __tablename__ = "triage_ai_events"
    id = Column(String(40), primary_key=True)
    record_id = Column(String(40), index=True)
    purpose = Column(String(40))
    model = Column(String(80))
    prompt_version = Column(String(40))
    input_summary = Column(Text)
    output = Column(Text)
    guard_result = Column(JSON, nullable=True)
    created_at = Column(UtcDateTime, default=lambda: datetime.now(timezone.utc))
