"""쇼츠 자동 제작기 - 화면(브라우저)으로 여는 프로그램."""
import os
import subprocess
import sys

import gradio as gr

from core import clip_mode, config, llm, topic_mode, tts, visuals

settings = config.load_settings()
PROVIDER_BY_LABEL = {label: key for key, label in llm.PROVIDERS.items()}


def _progress(p):
    return lambda frac, desc: p(frac, desc=desc)


def _error(e):
    raise gr.Error(str(e), duration=None)


# ---------- 🅰 주제로 만들기 ----------
def ui_write_script(topic, seconds, progress=gr.Progress()):
    if not topic.strip():
        raise gr.Error("주제를 먼저 적어 주세요.")
    progress(0.1, desc="AI가 대본 쓰는 중... (10초~1분)")
    try:
        title, lines, keywords = topic_mode.write_script(topic.strip(), settings, int(seconds))
    except Exception as e:
        _error(e)
    return title, "\n".join(lines), keywords


def ui_make_topic_video(title, script, keywords, progress=gr.Progress()):
    lines = [l for l in script.splitlines() if l.strip()]
    if not lines:
        raise gr.Error("대본이 비어 있어요. 먼저 '대본 만들기'를 눌러 주세요.")
    try:
        out = topic_mode.make_video(title, lines, keywords or [], settings, _progress(progress))
    except Exception as e:
        _error(e)
    return out, f"✅ 저장했어요: {out}"


# ---------- 🅱 긴 영상 잘라 만들기 ----------
def ui_make_clips(src, count, progress=gr.Progress()):
    if not src:
        raise gr.Error("긴 영상 파일을 먼저 넣어 주세요.")
    try:
        outputs, notes = clip_mode.make_shorts(src, settings, int(count), _progress(progress))
    except Exception as e:
        _error(e)
    return outputs, outputs[0] if outputs else None, "✅ 저장 위치: " + config.output_dir(settings) + "\n\n" + notes


# ---------- ⚙ 설정 ----------
def ui_status():
    ok, msg = llm.check(settings)
    pexels = "Pexels 키 있음 (배경 영상 사용)" if visuals.has_key(settings) else "Pexels 키 없음 (색깔 배경 사용)"
    return f"{'🟢' if ok else '🔴'} {msg}\n🎬 {pexels}\n📁 저장 위치: {settings['output_dir']}"


def ui_ai_status():
    ok, msg = llm.check(settings)
    return f"{'🟢' if ok else '🔴'} {msg}"


def ui_pick_provider(label):
    settings["provider"] = PROVIDER_BY_LABEL[label]
    config.save_settings(settings)
    return ui_ai_status()


def ui_save_settings(output_dir, local_model, claude_key, claude_model, openai_key, openai_model,
                     gemini_key, gemini_model, voice_label, rate, pexels_key):
    d = config.DEFAULTS
    settings.update({
        "output_dir": output_dir.strip() or d["output_dir"],
        "ollama_model": local_model.strip() or d["ollama_model"],
        "claude_key": claude_key.strip(),
        "claude_model": claude_model.strip() or d["claude_model"],
        "openai_key": openai_key.strip(),
        "openai_model": openai_model.strip() or d["openai_model"],
        "gemini_key": gemini_key.strip(),
        "gemini_model": gemini_model.strip() or d["gemini_model"],
        "voice": tts.VOICES.get(voice_label, d["voice"]),
        "voice_rate": f"{int(rate):+d}%",
        "pexels_key": pexels_key.strip(),
    })
    config.save_settings(settings)
    return "💾 저장했어요! (저장 위치를 바꿨다면 프로그램을 껐다 다시 켜 주세요)\n" + ui_status(), ui_ai_status()


def ui_open_folder():
    path = config.output_dir(settings)
    if sys.platform == "win32":
        os.startfile(path)
    else:
        subprocess.Popen(["xdg-open" if sys.platform.startswith("linux") else "open", path])
    return f"📁 {path}"


def voice_label():
    for label, code in tts.VOICES.items():
        if code == settings["voice"]:
            return label
    return next(iter(tts.VOICES))


with gr.Blocks(title="쇼츠 자동 제작기") as demo:
    gr.Markdown("# 🎬 쇼츠 자동 제작기\n완성된 영상은 **바탕화면 › 쇼츠** 폴더에 저장돼요.")
    with gr.Row():
        provider = gr.Dropdown(list(llm.PROVIDERS.values()), label="🤖 대본을 쓸 AI",
                               value=llm.PROVIDERS[settings["provider"]], scale=2)
        provider_msg = gr.Textbox(label="AI 상태", value=ui_ai_status,
                                  interactive=False, scale=3)
    provider.change(ui_pick_provider, provider, provider_msg)

    with gr.Tab("🅰 주제로 만들기"):
        with gr.Row():
            topic = gr.Textbox(label="① 주제", placeholder="예: 고양이가 상자를 좋아하는 이유", scale=4)
            seconds = gr.Slider(20, 60, value=45, step=5, label="영상 길이(초)", scale=1)
        write_btn = gr.Button("② 대본 만들기", variant="primary")
        title = gr.Textbox(label="제목 (화면 위에 나와요, 고쳐도 돼요)")
        script = gr.Textbox(label="대본 (한 줄 = 한 장면, 마음대로 고쳐도 돼요)", lines=8)
        keywords = gr.State([])
        make_btn = gr.Button("③ 영상 만들기", variant="primary")
        topic_result = gr.Video(label="완성된 쇼츠", height=560)
        topic_msg = gr.Markdown()
        write_btn.click(ui_write_script, [topic, seconds], [title, script, keywords])
        make_btn.click(ui_make_topic_video, [title, script, keywords], [topic_result, topic_msg])

    with gr.Tab("🅱 긴 영상 잘라 만들기"):
        src = gr.File(label="① 긴 영상 파일을 여기에 끌어다 놓으세요", file_types=["video"], type="filepath")
        count = gr.Slider(1, 5, value=3, step=1, label="쇼츠 몇 개 만들까요?")
        clip_btn = gr.Button("② 쇼츠 만들기", variant="primary")
        gr.Markdown("※ 1시간짜리 영상이면 10~20분 정도 걸릴 수 있어요. 처음 한 번은 음성 인식 AI를 내려받느라 더 걸려요.")
        clip_preview = gr.Video(label="첫 번째 쇼츠 미리보기", height=560)
        clip_files = gr.Files(label="만들어진 쇼츠 전체")
        clip_msg = gr.Textbox(label="결과", lines=6)
        clip_btn.click(ui_make_clips, [src, count], [clip_files, clip_preview, clip_msg])

    with gr.Tab("⚙ 설정"):
        status = gr.Textbox(label="상태", lines=3, value=ui_status)
        with gr.Row():
            refresh_btn = gr.Button("상태 다시 확인")
            open_btn = gr.Button("📁 저장 폴더 열기")
        out_dir = gr.Textbox(label="저장 위치", value=settings["output_dir"])
        with gr.Accordion("🏠 내 컴퓨터 AI (무료)", open=False):
            local_model = gr.Textbox(label="모델 이름 (Ollama)", value=settings["ollama_model"])
        with gr.Accordion("💳 Claude 키", open=False):
            gr.Markdown("https://console.anthropic.com 에서 가입 → API Keys → Create Key")
            claude_key = gr.Textbox(label="Claude 키", value=settings["claude_key"], type="password")
            claude_model = gr.Textbox(label="모델 이름", value=settings["claude_model"])
        with gr.Accordion("💳 ChatGPT 키", open=False):
            gr.Markdown("https://platform.openai.com/api-keys 에서 가입 → Create new secret key")
            openai_key = gr.Textbox(label="ChatGPT 키", value=settings["openai_key"], type="password")
            openai_model = gr.Textbox(label="모델 이름", value=settings["openai_model"])
        with gr.Accordion("💳 Gemini 키", open=False):
            gr.Markdown("https://aistudio.google.com/apikey 에서 구글 계정으로 로그인 → Create API key")
            gemini_key = gr.Textbox(label="Gemini 키", value=settings["gemini_key"], type="password")
            gemini_model = gr.Textbox(label="모델 이름", value=settings["gemini_model"])
        voice = gr.Dropdown(list(tts.VOICES), label="목소리", value=voice_label())
        rate = gr.Slider(-30, 50, value=int(settings["voice_rate"].rstrip("%")), step=5,
                         label="말하는 속도 (%)")
        pexels = gr.Textbox(label="Pexels 키 (없으면 색깔 배경으로 만들어요)", value=settings["pexels_key"],
                            type="password")
        gr.Markdown("Pexels 키는 https://www.pexels.com/api/ 에서 무료로 받을 수 있어요.")
        save_btn = gr.Button("💾 설정 저장", variant="primary")
        refresh_btn.click(ui_status, None, status)
        open_btn.click(ui_open_folder, None, status)
        save_btn.click(ui_save_settings, [out_dir, local_model, claude_key, claude_model, openai_key,
                                          openai_model, gemini_key, gemini_model, voice, rate, pexels],
                       [status, provider_msg])


if __name__ == "__main__":
    demo.queue().launch(inbrowser=True, server_name="127.0.0.1",
                        allowed_paths=[config.output_dir(settings)])
