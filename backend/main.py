"""预检分诊训练系统 — 独立版本"""
import os, asyncio, uuid, time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session
from database import init_db, engine, get_db
from routers import triage, auth
from logger import audit_logger

_MAX_REQUEST_BYTES = int(os.getenv("MAX_REQUEST_BYTES", str(10 * 1024 * 1024)))


def _seed_yjfz_users():
    """初始化YJFZ独立用户（与主系统不冲突）"""
    from database import SessionLocal
    from models import User
    from auth import hash_password
    db = SessionLocal()
    try:
        seeds = [
            ("teacher1", "teacher123", "teacher", "预检分诊教师", None),
            ("reviewer1", "reviewer123", "reviewer", "病例审核专家", None),
            ("admin", "admin123", "admin", "系统管理员", None),
        ]
        for i in range(1, 6):
            seeds.append((f"student{i}", "123456", "student", f"新护士{i}", f"YJFZ{i:03d}"))
        created = 0
        for username, password, role, display_name, student_id in seeds:
            if db.query(User).filter(User.username == username).first():
                continue
            db.add(User(username=username, password_hash=hash_password(password), role=role, display_name=display_name, student_id=student_id))
            created += 1
        db.commit()
        if created:
            print(f"预检分诊默认账号初始化完成: {created}")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    _seed_yjfz_users()
    from rate_limiter import _limiter as rate_limiter

    async def _cleanup_loop():
        while True:
            await asyncio.sleep(600)
            rate_limiter.cleanup()

    cleanup_task = asyncio.create_task(_cleanup_loop())
    yield
    cleanup_task.cancel()

    try:
        from services.llm_service import _shared_client
        if _shared_client:
            await _shared_client.aclose()
    finally:
        engine.dispose()


app = FastAPI(title="预检分诊训练系统", version="1.0.0", lifespan=lifespan)

_cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3010,http://localhost:8010").split(",")
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in _cors_origins if o.strip()],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def limit_request_size(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > _MAX_REQUEST_BYTES:
        return JSONResponse(
            status_code=413,
            content={"detail": f"请求体过大，最大允许 {_MAX_REQUEST_BYTES // (1024*1024)}MB"},
        )
    return await call_next(request)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    rid = request.headers.get("X-Request-ID", str(uuid.uuid4())[:8])
    request.state.request_id = rid
    t0 = time.time()
    response = await call_next(request)
    duration_ms = round((time.time() - t0) * 1000)
    audit_logger.info("%s %s -> %s (%sms)", request.method, request.url.path, response.status_code, duration_ms, extra={"request_id": rid})
    response.headers["X-Request-ID"] = rid
    return response


app.include_router(auth.router)
app.include_router(triage.router)


@app.get("/api")
def root():
    return {"message": "预检分诊训练系统 API", "version": "1.0.0"}


@app.get("/api/health")
def health_check(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "connected", "system": "YJFZ"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"数据库连接失败: {str(e)}")

FRONTEND_DIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend", "dist")
if os.path.isdir(FRONTEND_DIST):
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
