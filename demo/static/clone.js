// The independent voice-creation form in the Web Demo: record a fixed sentence with the browser's microphone or upload a wav / mp3,
// remove the silence at both ends, check the length, play it back, then POST it (as a 24 kHz mono WAV) with the
// transcript, a name, the gender and the speaker's consent to the server's /clone.
//   CloneDialog.mount(element, { url, fields, onCloned(json), onCancel })   builds the form into element
//   CloneDialog.open() / close() / applyLang("en" | "zh")
const CloneDialog = (() => {
  // A reference recording of the web pages is 3-5 s after trimming its silence: the longer the reference, the slower
  // every streaming step (the DiT always runs over reference + generated audio); up to 5 s the page's default preroll
  // (1.5 s) keeps playback without stalls on the board. The SDK and clone.py accept 3-10 s.
  const SR = 24000, MIN_S = 3, MAX_S = 5, REC_S = 7;          // REC_S: raw recording time (silence included)
  // the sentence a speaker reads when recording a voice, per language: calm, everyday wording, about 4-5 s at a
  // normal pace; it is also the transcript of the recording
  const SCRIPTS = {
    Chinese: "今天天气很好，我们一起去公园散散步吧。",
    English: "The morning sun is rising slowly above the quiet hills.",
    Japanese: "今日はいい天気なので、公園まで散歩に行きます。",
    Korean: "오늘은 날씨가 좋아서 공원까지 산책을 갑니다.",
    German: "Heute ist das Wetter schön, ich gehe im Park spazieren.",
    French: "Aujourd'hui il fait beau, je vais me promener au parc.",
    Spanish: "Hoy hace buen tiempo, voy a pasear por el parque.",
    Italian: "Oggi il tempo è bello, vado a passeggiare nel parco.",
    Russian: "Сегодня хорошая погода, я пойду гулять в парк."
  };
  const STR = {
    zh: {
      c_checking: "正在检查板端克隆模型…", c_setup_title: "需要先安装克隆模型",
      c_setup_help: "克隆为独立业务功能，请从上游 Hugging Face 获取克隆模型后点击重新检查。",
      c_setup_dir: "模型安装目录：", c_setup_missing: "缺少或未完整下载：", c_recheck: "重新检查",
      c_setup_guide: "安装说明", c_check_failed: "无法检查克隆模型，请确认服务连接后重试。",
      c_title: "克隆新音色", c_limit: "参考录音需要 3–5 秒（去掉首尾静音后）：参考录音更长时，合成变慢，播放会卡顿。",
      c_mode_rec: "🎤 录音", c_mode_file: "📁 上传文件", c_lang: "语种",
      c_read: "请用正常语速朗读：", c_rec_start: "● 录音", c_rec_stop: "■ 停止", c_rec_again: "● 重录",
      c_count: n => `${n}…`,
      c_need_https: u => `浏览器只允许在 HTTPS 页面使用麦克风：请打开 ${u}（第一次需要确认证书提示）。`,
      c_no_mic: "无法使用麦克风（没有设备或未授权）",
      c_silent: "未录到有效声音。请检查麦克风是否静音、输入设备和音量，然后重新录制。",
      c_quiet: "录音音量偏低，建议靠近麦克风重新录制；请先试听，确认声音清晰。",
      c_listen: "请先试听录音，确认能听清自己的声音，再开始克隆。",
      c_heard: "我已试听，能听清录音中的本人声音",
      c_play_failed: "试听失败，请检查浏览器播放权限和输出设备后重试。",
      c_file: "参考录音：wav 或 mp3，3–5 秒，单人说话、无背景音", c_text: "录音里说的话（逐字填写）",
      c_play: "▶ 试听", c_stop: "■ 停止", c_name: "名称", c_name_ph: "例如：我的声音", female: "女", male: "男",
      c_consent: "我确认说话人同意克隆其声音", cancel: "取消", c_run: "开始克隆",
      c_sec: d => `${d} 秒`, c_ok_but: "（可以用，推荐 4–5 秒）",
      c_need: "（需要 3–5 秒：参考录音更长时，合成变慢，播放会卡顿）",
      c_trimmed: d => `（已去掉首尾静音，原长 ${d} 秒）`, c_only: "只支持 .wav 或 .mp3 文件",
      c_low_sr: sr => `采样率 ${sr} Hz 太低（至少 16 kHz）`, c_bad_file: "无法解码这个文件",
      c_busy: "克隆中…（第一次需要多等几秒加载模型）", c_failed: "克隆失败",
      c_err: { consent: "请勾选授权确认", name: "请填写名称", text: "请填写录音里说的话",
               text_long: "录音里说的话太长（最多 200 字）", format: "无法读取这段音频",
               length: "录音时长需要在 3–5 秒之间", sample_rate: "录音采样率太低（至少 16 kHz）",
               limit: "克隆音色已达上限，请先删除不用的", internal: "服务端出错",
               silent: "录音没有有效声音，请检查麦克风后重新录制",
               unavailable: "克隆模型尚未就绪，请查看安装说明和服务端提示" }
    },
    en: {
      c_checking: "Checking the cloning models on the board…", c_setup_title: "Install the cloning models first",
      c_setup_help: "Download the separate cloning assets from upstream Hugging Face, then click Recheck.",
      c_setup_dir: "Model directory: ", c_setup_missing: "Missing or incomplete: ", c_recheck: "Recheck",
      c_setup_guide: "Installation guide", c_check_failed: "Cannot check the cloning models. Check the server connection and retry.",
      c_title: "Clone a new voice",
      c_limit: "The reference must be 3–5 s long (after trimming silence): a longer one makes synthesis slower and "
        + "playback stutter.",
      c_mode_rec: "🎤 Record", c_mode_file: "📁 Upload a file", c_lang: "Language",
      c_read: "Read aloud at a normal pace:", c_rec_start: "● Record", c_rec_stop: "■ Stop",
      c_rec_again: "● Record again", c_count: n => `${n}…`,
      c_need_https: u => `Browsers allow the microphone on HTTPS pages only: open ${u} (accept the certificate warning `
        + "the first time).",
      c_no_mic: "No microphone (none found or access denied)",
      c_silent: "No usable sound was recorded. Check microphone mute, input device and volume, then record again.",
      c_quiet: "The recording is quiet. Move closer to the microphone and record again, or listen and confirm it is clear.",
      c_listen: "Listen to the recording and confirm you can clearly hear your own voice before cloning.",
      c_heard: "I listened and can clearly hear my own voice in the recording",
      c_play_failed: "Playback failed. Check browser playback permissions and the output device, then retry.",
      c_file: "Reference recording: wav or mp3, 3–5 s, one speaker, no background sound",
      c_text: "What is said in the recording (word for word)", c_play: "▶ Play", c_stop: "■ Stop", c_name: "Name",
      c_name_ph: "e.g. My voice", female: "Female", male: "Male",
      c_consent: "I confirm that the speaker agrees to have their voice cloned", cancel: "Cancel", c_run: "Clone",
      c_sec: d => `${d} s`, c_ok_but: " (usable; 4–5 s recommended)",
      c_need: " (must be 3–5 s: a longer reference makes synthesis slower and playback stutter)",
      c_trimmed: d => ` (silence at both ends removed, was ${d} s)`, c_only: "Only .wav or .mp3 files",
      c_low_sr: sr => `Sample rate ${sr} Hz is too low (at least 16 kHz)`, c_bad_file: "Cannot decode this file",
      c_busy: "Cloning… (the first time takes a few seconds more to load the models)", c_failed: "Cloning failed",
      c_err: { consent: "Please confirm the speaker's consent", name: "Please enter a name",
               text: "Please enter what is said in the recording",
               text_long: "The transcript is too long (at most 200 characters)", format: "Cannot read this audio",
               length: "The recording must be 3–5 s long", sample_rate: "Sample rate too low (at least 16 kHz)",
               limit: "Too many cloned voices: delete one first", internal: "Server error",
               silent: "No usable sound in the recording. Check the microphone and record again",
               unavailable: "The cloning models are not ready; see the installation guide and server message" }
    }
  };
  const CSS = `
    .cv-f { margin-top:10px; } .cv-f > label { display:block; margin-bottom:4px; }
    .cv-row { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
    .cv-hide { display:none !important; }
    #c-text { width:100%; height:56px; resize:vertical; }
    #c-script { padding:10px 12px; background:var(--sel, #f0f6ff); border:1px solid var(--line, #d0d7de);
                border-radius:6px; font-size:16px; line-height:1.6; }
    #c-meter { display:inline-block; width:120px; height:8px; background:var(--bg, #f6f8fa);
               border:1px solid var(--line, #d0d7de); border-radius:4px; overflow:hidden; vertical-align:middle; }
    #c-meter > i { display:block; height:100%; width:0; background:var(--ok, #1a7f37); }
    #c-time { font-size:12px; color:var(--muted, #656d76); min-width:64px; }
    #c-info { font-size:12px; margin-left:8px; } #c-msg { font-size:13px; margin-top:8px; min-height:18px; }
    #c-secure, #c-limit { font-size:12px; color:var(--muted, #656d76); }
    #c-setup p { margin:8px 0; font-size:13px; }
    #c-setup .cv-setup-path { display:block; max-width:100%; overflow:hidden; text-overflow:ellipsis;
                             white-space:nowrap; font-size:12px; }
    #c-setup pre.cv-setup-code { box-sizing:border-box; width:100%; max-width:100%; height:148px;
      margin:10px 0; padding:10px 12px; border:1px solid var(--line, #d0d7de); border-radius:6px;
      background:var(--bg, #f6f8fa); overflow:auto; white-space:pre; overflow-wrap:normal; word-break:normal;
      font:12px/1.6 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
    #c-setup pre.cv-setup-code code { font:inherit; }`;
  const HTML = `
    <h3 data-ci18n="c_title"></h3>
    <div id="c-setup" role="status" aria-live="polite"></div>
    <fieldset id="c-inputs" disabled style="border:0;padding:0;margin:0;min-width:0">
    <div class="cv-row" id="c-modes" style="margin-top:8px">
      <button class="chip on" data-mode="rec" data-ci18n="c_mode_rec"></button>
      <button class="chip" data-mode="file" data-ci18n="c_mode_file"></button>
    </div>
    <div class="cv-f" id="c-limit" data-ci18n="c_limit"></div>
    <div id="c-rec">
      <div class="cv-f cv-row"><label data-ci18n="c_lang"></label><select id="c-lang"></select></div>
      <div class="cv-f"><label data-ci18n="c_read"></label><div id="c-script"></div></div>
      <div class="cv-f cv-row"><button id="c-recbtn" data-ci18n="c_rec_start"></button>
        <span id="c-meter"><i></i></span><span id="c-time"></span></div>
      <div class="cv-f" id="c-secure"></div>
    </div>
    <div id="c-up" class="cv-hide">
      <div class="cv-f"><label data-ci18n="c_file"></label>
        <input type="file" id="c-file" accept=".wav,.mp3,audio/wav,audio/x-wav,audio/mpeg"></div>
      <div class="cv-f"><label data-ci18n="c_text"></label><textarea id="c-text" maxlength="200"></textarea></div>
    </div>
    <div class="cv-f cv-row"><button id="c-play" class="ghost small" disabled data-ci18n="c_play"></button>
      <span id="c-info"></span></div>
    <div class="cv-f"><label><input type="checkbox" id="c-heard" disabled> <span data-ci18n="c_heard"></span></label></div>
    <div class="cv-f cv-row">
      <label><span data-ci18n="c_name"></span> <input type="text" id="c-name" maxlength="20"></label>
      <label><input type="radio" name="c-gender" value="female" checked> <span data-ci18n="female"></span></label>
      <label><input type="radio" name="c-gender" value="male"> <span data-ci18n="male"></span></label>
    </div>
    <div class="cv-f"><label><input type="checkbox" id="c-consent"> <span data-ci18n="c_consent"></span></label></div>
    </fieldset>
    <div class="cv-f cv-row"><span style="flex:1"></span>
      <button id="c-cancel" class="ghost" data-ci18n="cancel"></button>
      <button id="c-run" disabled data-ci18n="c_run"></button></div>
    <div id="c-msg"></div>`;

  let o = {}, lang = "en", wav = null, player = null, mode = "rec", rec = null;
  let savedRetry = null, savedCloneSeconds = 0;
  let setup = null, checking = false, setupError = false, checkVersion = 0;
  const $ = id => document.getElementById(id);
  const t = k => STR[lang][k];

  // Match the server's conservative AC-level check; this does not identify speech.
  function audioQuality(x, sr) {
    const width = Math.max(1, Math.round(sr * 0.02));
    let active = 0, maxRms = 0;
    for (let start = 0; start + width <= x.length; start += width) {
      let sum = 0;
      for (let i = start; i < start + width; i++) {
        if (!Number.isFinite(x[i])) return "silent";
        sum += x[i];
      }
      const mean = sum / width;
      let energy = 0;
      for (let i = start; i < start + width; i++) energy += (x[i] - mean) ** 2;
      const rms = Math.sqrt(energy / width);
      maxRms = Math.max(maxRms, rms);
      if (rms >= 1e-4) active += width;
    }
    if (active / sr < 0.2) return "silent";
    return maxRms < 0.0031623 ? "quiet" : "ok";
  }

  // silence at both ends of a recording: 20 ms frames, the noise floor = the 10 % quietest frames, speech = 3 frames
  // in a row more than 12 dB above the floor and no more than 40 dB below the loudest frame (quiet microphones keep
  // their speech); 0.2 s kept before / after the speech, 10 ms fades. Pauses inside are kept; a recording without a
  // clear floor (noisy room) is returned as it is.
  function trimSilence(x, sr) {
    const W = Math.round(0.02 * sr), n = Math.floor(x.length / W);
    if (n < 10) return x;
    const db = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      let e = 0; for (let k = i * W; k < (i + 1) * W; k++) e += x[k] * x[k];
      db[i] = 10 * Math.log10(e / W + 1e-12);
    }
    const sorted = Float32Array.from(db).sort(), thr = Math.max(sorted[Math.floor(0.1 * n)] + 12, sorted[n - 1] - 40);
    const loud = i => db[i] > thr && db[i + 1] > thr && db[i + 2] > thr;
    let on = -1, off = -1;
    for (let i = 0; i + 2 < n; i++) if (loud(i)) { on = i; break; }
    for (let i = n - 3; i >= 0; i--) if (loud(i)) { off = i + 2; break; }
    if (on < 0) return x;
    const a = Math.max(0, on * W - Math.round(0.2 * sr)), b = Math.min(x.length, (off + 1) * W + Math.round(0.2 * sr));
    const y = x.slice(a, b), f = Math.min(Math.round(0.01 * sr), y.length >> 1);
    for (let i = 0; i < f; i++) { y[i] *= i / f; y[y.length - 1 - i] *= i / f; }
    return y;
  }

  // sample rate of the source file (decodeAudioData resamples, so it is read from the header): WAV fmt chunk / first
  // MPEG audio frame (after an ID3v2 tag); null if not found
  function sourceRate(b, isMp3) {
    const d = new DataView(b);
    if (!isMp3) {
      if (b.byteLength < 12 || d.getUint32(0) !== 0x52494646) return null;            // "RIFF"
      for (let i = 12; i + 16 <= b.byteLength; i += 8 + d.getUint32(i + 4, true) + (d.getUint32(i + 4, true) & 1))
        if (d.getUint32(i) === 0x666d7420) return d.getUint32(i + 12, true);           // "fmt " chunk: sample rate
      return null;
    }
    let i = 0;
    if (b.byteLength > 10 && d.getUint8(0) === 0x49 && d.getUint8(1) === 0x44 && d.getUint8(2) === 0x33)
      i = 10 + ((d.getUint8(6) & 127) << 21 | (d.getUint8(7) & 127) << 14 | (d.getUint8(8) & 127) << 7
                | (d.getUint8(9) & 127));
    for (; i + 4 < b.byteLength; i++) {
      if (d.getUint8(i) !== 0xFF || (d.getUint8(i + 1) & 0xE0) !== 0xE0) continue;
      const ver = (d.getUint8(i + 1) >> 3) & 3, idx = (d.getUint8(i + 2) >> 2) & 3;
      if (ver === 1 || idx === 3) continue;
      return [[11025, 12000, 8000], null, [22050, 24000, 16000], [44100, 48000, 32000]][ver][idx];
    }
    return null;
  }

  function encodeWav(f, sr) {
    const b = new ArrayBuffer(44 + f.length * 2), d = new DataView(b);
    const w = (o, s) => { for (let i = 0; i < s.length; i++) d.setUint8(o + i, s.charCodeAt(i)); };
    w(0, "RIFF"); d.setUint32(4, 36 + f.length * 2, true); w(8, "WAVE"); w(12, "fmt "); d.setUint32(16, 16, true);
    d.setUint16(20, 1, true); d.setUint16(22, 1, true); d.setUint32(24, sr, true); d.setUint32(28, sr * 2, true);
    d.setUint16(32, 2, true); d.setUint16(34, 16, true); w(36, "data"); d.setUint32(40, f.length * 2, true);
    for (let i = 0; i < f.length; i++)
      d.setInt16(44 + 2 * i, Math.max(-32768, Math.min(32767, Math.round(f[i] * 32767))), true);
    return new Blob([b], { type: "audio/wav" });
  }

  function msg(s, cls) { $("c-msg").textContent = s; $("c-msg").className = cls || ""; }
  function ready() {
    if (savedRetry) {
      $("c-run").disabled = false;
      $("c-run").textContent = lang === "zh" ? "重试加载已保存音色" : "Retry loading saved voice";
      return;
    }
    $("c-run").textContent = t("c_run");
    $("c-run").disabled = !(setup?.ready && !checking && wav && (mode === "rec" || $("c-text").value.trim()) && $("c-name").value.trim()
                            && $("c-consent").checked && $("c-heard").checked);
  }
  function stopPlayer() { if (player) { player.pause(); player = null; $("c-play").textContent = t("c_play"); } }
  function resetClip() {
    savedRetry = null;
    $("c-heard").checked = false; $("c-heard").disabled = true;
    wav = null; $("c-play").disabled = true; $("c-info").textContent = ""; msg(""); stopPlayer(); ready();
  }

  // a recording or a decoded file (mono, 24 kHz) -> trimmed, checked, ready to clone
  function takeClip(mono, srcRate) {
    resetClip();
    const y = trimSilence(mono, SR), dur = y.length / SR, ok = dur >= MIN_S && dur <= MAX_S;
    const quality = audioQuality(y, SR);
    if (quality === "silent") {
      $("c-info").textContent = t("c_sec")(dur.toFixed(1));
      $("c-info").className = "bad"; msg(t("c_silent"), "bad"); return;
    }
    $("c-info").textContent = t("c_sec")(dur.toFixed(1)) + (srcRate ? ` · ${srcRate} Hz` : "") +
      (ok ? (dur < 4 ? t("c_ok_but") : " ✓") : t("c_need")) +
      (y.length < mono.length - SR / 10 ? t("c_trimmed")((mono.length / SR).toFixed(1)) : "");
    $("c-info").className = ok ? "ok" : "bad";
    const blob = encodeWav(y, SR);
    $("c-play").disabled = false;
    $("c-play").onclick = async () => {
      if (player) { stopPlayer(); return; }
      const url = URL.createObjectURL(blob), current = new Audio(url);
      player = current;
      current.onended = () => { URL.revokeObjectURL(url); if (player === current) stopPlayer(); };
      current.onerror = () => {
        URL.revokeObjectURL(url);
        if (player !== current) return;
        stopPlayer(); $("c-heard").checked = false; $("c-heard").disabled = true;
        msg(t("c_play_failed"), "bad"); ready();
      };
      try {
        await current.play();
        if (player !== current) { current.pause(); URL.revokeObjectURL(url); return; }
        $("c-play").textContent = t("c_stop"); $("c-heard").disabled = false;
      } catch (e) { current.onerror(); }
    };
    wav = ok ? blob : null;
    if (ok) msg(t(quality === "quiet" ? "c_quiet" : "c_listen"));
    ready();
  }

  function setMode(m) {
    mode = m;
    $("c-modes").querySelectorAll("[data-mode]").forEach(b => b.classList.toggle("on", b.dataset.mode === m));
    $("c-rec").classList.toggle("cv-hide", m !== "rec");
    $("c-up").classList.toggle("cv-hide", m !== "file");
    resetClip();
  }
  function renderScript() { $("c-script").textContent = SCRIPTS[$("c-lang").value] || ""; }

  // microphone: raw sound (no echo cancellation / noise suppression / gain control), a 3 s count-down, at most REC_S
  async function toggleRec() {
    if (rec) { rec.stop(); return; }
    resetClip();
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false,
                                                                      autoGainControl: false, channelCount: 1 } });
    } catch (e) { msg(t("c_no_mic"), "bad"); return; }
    const actx = new (window.AudioContext || window.webkitAudioContext)(), src = actx.createMediaStreamSource(stream);
    try { await actx.resume(); } catch (e) {
      stream.getTracks().forEach(k => k.stop()); actx.close(); msg(t("c_no_mic"), "bad"); return;
    }
    const proc = actx.createScriptProcessor(4096, 1, 1), parts = [];
    const btn = $("c-recbtn"), meter = $("c-meter").firstChild;
    let n = 0, live = false;
    rec = { stop() {
      if (!rec) return;
      rec = null; live = false;
      proc.disconnect(); src.disconnect(); stream.getTracks().forEach(k => k.stop());
      btn.textContent = t("c_rec_again"); btn.disabled = false; meter.style.width = "0";
      const sr = actx.sampleRate; actx.close();
      if (!n) { msg(t("c_silent"), "bad"); return; }
      const x = new Float32Array(n); let p = 0; for (const q of parts) { x.set(q, p); p += q.length; }
      const off = new OfflineAudioContext(1, Math.ceil(n * SR / sr), SR), b = off.createBuffer(1, n, sr);
      b.copyToChannel(x, 0);
      const bs = off.createBufferSource(); bs.buffer = b; bs.connect(off.destination); bs.start();
      off.startRendering().then(r => takeClip(r.getChannelData(0).slice(), sr))
        .catch(() => { resetClip(); msg(t("c_bad_file"), "bad"); });
    } };
    proc.onaudioprocess = e => {
      const d = e.inputBuffer.getChannelData(0);
      let m = 0; for (let i = 0; i < d.length; i++) m = Math.max(m, Math.abs(d[i]));
      meter.style.width = Math.min(100, Math.round(100 * Math.sqrt(m))) + "%";
      if (!live) return;
      parts.push(new Float32Array(d)); n += d.length;
      $("c-time").textContent = `${(n / actx.sampleRate).toFixed(1)} / ${REC_S} s`;
      if (n / actx.sampleRate >= REC_S && rec) rec.stop();
    };
    src.connect(proc); proc.connect(actx.destination);
    btn.disabled = true;
    for (let k = 3; k > 0 && rec; k--) {
      btn.textContent = t("c_count")(k);
      await new Promise(r => setTimeout(r, 1000));
    }
    if (!rec) return;
    live = true; btn.disabled = false; btn.textContent = t("c_rec_stop");
  }

  async function onFile() {
    resetClip();
    const file = $("c-file").files[0];
    if (!file) return;
    const isMp3 = /\.mp3$/i.test(file.name), isWav = /\.wav$/i.test(file.name);
    if (!isMp3 && !isWav) { $("c-info").textContent = t("c_only"); $("c-info").className = "bad"; return; }
    try {
      const raw = await file.arrayBuffer();
      const sr0 = sourceRate(raw, isMp3);
      if (sr0 && sr0 < 16000) { $("c-info").textContent = t("c_low_sr")(sr0); $("c-info").className = "bad"; return; }
      const ab = await new OfflineAudioContext(1, SR, SR).decodeAudioData(raw.slice(0));
      const n = ab.length, mono = new Float32Array(n);
      for (let c = 0; c < ab.numberOfChannels; c++) {
        const x = ab.getChannelData(c);
        for (let i = 0; i < n; i++) mono[i] += x[i] / ab.numberOfChannels;
      }
      takeClip(mono, sr0);
    } catch (e) { $("c-info").textContent = t("c_bad_file"); $("c-info").className = "bad"; }
  }

  async function loadSaved() {
    $("c-run").disabled = true;
    $("c-msg").dataset.state = "saved/waiting-to-load";
    msg(lang === "zh" ? "音色已保存，正在等待当前合成结束并加载…" : "Voice saved. Waiting for synthesis to finish, then loading…");
    try {
      const response = await fetch(savedRetry, {method:"POST"});
      const result = await response.json();
      if (!response.ok && result.state === "saved/waiting-to-load") {
        msg(result.message, ""); $("c-msg").dataset.state = result.state; ready(); return;
      }
      if (!response.ok) throw new Error(result.message || "Load failed");
      if (result.state !== "ready") throw new Error("Saved voice is not ready");
      savedRetry = null; result.clone_s = savedCloneSeconds;
      $("c-msg").dataset.state = "ready";
      resetClip();
      if (o.onCloned) await o.onCloned(result);
    } catch (error) {
      $("c-msg").dataset.state = "saved/load-failed";
      msg((lang === "zh" ? "音色已保存但加载失败，可直接重试，无需重新上传。 " : "Voice saved; loading failed. Retry without uploading again. ") + error.message,"bad");
      ready();
    }
  }

  async function submit() {
    if (savedRetry) { await loadSaved(); return; }
    ready();
    if ($("c-run").disabled) return;
    const fd = new FormData();
    fd.append("audio", wav, "ref.wav");
    fd.append("text", mode === "rec" ? SCRIPTS[$("c-lang").value] : $("c-text").value.trim());
    fd.append("name", $("c-name").value.trim());
    fd.append("gender", document.querySelector('input[name="c-gender"]:checked').value);
    fd.append("consent", $("c-consent").checked ? "1" : "0");
    for (const [k, v] of Object.entries(o.fields || {})) fd.append(k, v);
    $("c-run").disabled = true; msg(t("c_busy"));
    try {
      const r = await fetch(o.url || "/clone", { method: "POST", body: fd });
      const j = await r.json();
      if (!r.ok) {
        if (j.error === "unavailable") await checkModels();
        msg((t("c_err")[j.error] || t("c_failed")) + ` (${j.message})`, "bad"); ready(); return;
      }
      if (j.state === "saved/waiting-to-load") {
        savedRetry = j.load_url; savedCloneSeconds = j.clone_s;
        await loadSaved(); return;
      }
      ["c-text", "c-name"].forEach(i => $(i).value = ""); $("c-file").value = ""; $("c-consent").checked = false;
      $("c-recbtn").textContent = t("c_rec_start"); $("c-time").textContent = "";
      resetClip();
      if (o.onCloned) await o.onCloned(j);
    } catch (e) { msg(t("c_failed") + ": " + e.message, "bad"); ready(); }
  }

  function applyLang(l) {
    lang = STR[l] ? l : "en";
    document.querySelectorAll("[data-ci18n]").forEach(e => e.textContent = t(e.getAttribute("data-ci18n")));
    $("c-name").placeholder = t("c_name_ph");
    renderSetup();
  }

  function renderSetup() {
    const box = $("c-setup");
    box.replaceChildren();
    $("c-inputs").disabled = checking || !setup?.ready;
    $("c-inputs").classList.toggle("cv-hide", checking || !setup?.ready);
    if (setup?.ready && !checking) { ready(); return; }
    const line = document.createElement("p");
    line.textContent = checking ? t("c_checking") : setupError ? t("c_check_failed") : t("c_setup_title");
    box.append(line);
    if (setup && !setup.ready) {
      const help = document.createElement("p"); help.textContent = t("c_setup_help"); box.append(help);
      const directory = document.createElement("p"); directory.textContent = t("c_setup_dir");
      const path = document.createElement("code"); path.className = "cv-setup-path";
      path.textContent = setup.directory; path.title = setup.directory; directory.append(path); box.append(directory);
      const missing = document.createElement("p");
      missing.textContent = t("c_setup_missing") + setup.missing.join(", "); box.append(missing);
      const pre = document.createElement("pre"), code = document.createElement("code");
      pre.className = "cv-setup-code"; code.textContent = setup.install_command;
      pre.append(code); box.append(pre);
    }
    const link = document.createElement("a");
    link.href = "https://github.com/APLUX-Pandora/fun-cosyvoice3-0.5b-2512-demo/blob/main/docs/VOICE_CLONING.md#1-prepare-the-environment-and-model-resources";
    link.textContent = t("c_setup_guide"); link.target = "_blank"; link.rel = "noopener"; box.append(link);
    const retry = document.createElement("button"); retry.type = "button";
    retry.textContent = t("c_recheck"); retry.disabled = checking;
    retry.style.marginLeft = "12px"; retry.onclick = checkModels; box.append(retry);
    ready();
  }

  async function checkModels() {
    const version = ++checkVersion;
    if (rec) rec.stop();
    checking = true; setupError = false; renderSetup();
    try {
      const response = await fetch(o.statusUrl || "/clone/status", { cache: "no-store" });
      if (!response.ok) throw new Error("status " + response.status);
      const value = await response.json();
      if (typeof value.ready !== "boolean" || !Array.isArray(value.missing)) throw new Error("invalid status");
      if (version !== checkVersion) return;
      setup = value;
    } catch (e) {
      if (version !== checkVersion) return;
      setup = null; setupError = true;
    }
    checking = false; renderSetup();
  }

  function mount(el, opts) {
    o = opts || {};
    const st = document.createElement("style"); st.textContent = CSS; document.head.appendChild(st);
    el.innerHTML = HTML;
    $("c-lang").innerHTML = Object.keys(SCRIPTS).map(l => `<option>${l}</option>`).join("");
    $("c-lang").value = "";
    $("c-lang").onchange = () => { renderScript(); resetClip(); };
    $("c-modes").onclick = e => { const b = e.target.closest("[data-mode]"); if (b) setMode(b.dataset.mode); };
    $("c-recbtn").onclick = toggleRec;
    $("c-file").onchange = onFile;
    ["c-text", "c-name"].forEach(i => $(i).addEventListener("input", ready));
    $("c-consent").onchange = ready;
    $("c-heard").onchange = ready;
    $("c-run").onclick = submit;
    $("c-cancel").classList.toggle("cv-hide", !o.onCancel);
    $("c-cancel").onclick = () => { close(); if (o.onCancel) o.onCancel(); };
    applyLang(o.lang || "en");
  }

  function open() {
    const secure = window.isSecureContext && navigator.mediaDevices;
    $("c-recbtn").disabled = !secure;
    $("c-secure").textContent = secure ? "" : t("c_need_https")(`https://${location.host}/`);
    if (!$("c-lang").value) $("c-lang").value = lang === "zh" ? "Chinese" : "English";
    renderScript();
    checkModels();
  }
  function close() { stopPlayer(); if (rec) rec.stop(); }

  return { mount, open, close, applyLang, SCRIPTS, trimSilence, audioQuality };
})();
