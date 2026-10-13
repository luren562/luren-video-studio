"""Agent 的可中断执行、检查点与渲染输入版本。无模型或数据库副作用。"""
from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import tempfile
import time
import zipfile
from contextlib import contextmanager
from pathlib import Path


class AgentError(RuntimeError):
    error_code = "agent_error"


class AgentCancelled(AgentError):
    error_code = "cancelled"


class AgentBudgetExceeded(AgentError):
    error_code = "budget_exhausted"


class AgentStopped(AgentBudgetExceeded):
    """A bounded business stop, with the original cause retained."""
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.error_code = code


@contextmanager
def execution_lock(path: Path):
    """OS lock survives neither a process crash nor a closed handle; file is retained."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise AgentStopped('already_running', '同一项目已有执行，禁止并发改写或重复调用') from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def input_files(root: Path) -> list[Path]:
    files = [p for name in ("src", "public") for p in (root / name).rglob("*") if p.is_file()]
    files += [p for p in root.iterdir() if p.is_file() and p.suffix in (".ts", ".js", ".json")]
    return sorted(files)


def input_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in input_files(root):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest()


def snapshot_inputs(root: Path, output: Path) -> None:
    files = input_files(root)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(root).as_posix())
        for name in ("SHOTBOOK.md", "PLAN.json"):
            path = root / name
            if path.is_file() and path not in files:
                archive.write(path, name)


def run_process(argv: list[str], cwd: Path, timeout: float, cancelled=lambda: False,
                output_limit: int = 24000, log_path: Path | None = None) -> dict:
    """只终止本函数创建的进程树；输出写临时文件，避免 PIPE 填满挂住。"""
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
    with (log_path.with_suffix('.stdout.log').open('w+b') if log_path else tempfile.TemporaryFile()) as stdout, \
         (log_path.with_suffix('.stderr.log').open('w+b') if log_path else tempfile.TemporaryFile()) as stderr:
        options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        process = subprocess.Popen(argv, cwd=str(cwd), stdout=stdout, stderr=stderr, **options)
        started = time.monotonic()
        try:
            while process.poll() is None:
                if cancelled():
                    raise AgentCancelled("任务已取消，已保留工程和候选视频")
                if time.monotonic() - started >= timeout:
                    raise AgentBudgetExceeded(f"命令执行超时（{timeout:.0f}s）")
                time.sleep(0.2)
        finally:
            if process.poll() is None:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=15)
                else:
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=15)
            if log_path:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                with log_path.open('wb') as log:
                    for stream in (stdout, stderr):
                        stream.seek(0)
                        while block := stream.read(1024 * 1024):
                            log.write(block)
        chunks = []
        for stream in (stdout, stderr):
            stream.seek(max(0, stream.tell() - output_limit))
            chunks.append(stream.read().decode("utf-8", errors="replace"))
        return {"exit": process.returncode, "output": "\n".join(chunks)[-output_limit:]}


def probe_video(path: Path, ffmpeg: str = "ffmpeg") -> dict:
    # 与 ffmpeg 使用同一安装目录；默认 PATH 安装则使用 ffprobe。
    binary = str(Path(ffmpeg).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe"))
    result = subprocess.run([binary, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                            capture_output=True, text=True, encoding="utf-8", timeout=30, check=True)
    data = json.loads(result.stdout)
    video = next((s for s in data["streams"] if s.get("codec_type") == "video"), None)
    if not video:
        raise AgentError("输出中没有视频轨")
    numerator, denominator = video.get("avg_frame_rate", "0/1").split("/")
    fps = float(numerator) / max(float(denominator), 1)
    duration = float(video.get("duration") or data["format"]["duration"])
    return {"width": int(video["width"]), "height": int(video["height"]), "fps": fps,
            "duration": duration, "frames": int(video.get("nb_frames") or round(duration * fps)),
            "has_audio": any(s.get("codec_type") == "audio" for s in data["streams"])}
