"use strict";

const $ = (id) => document.getElementById(id);
const csrf = document.querySelector('meta[name="csrf-token"]').content;
let video = null;
let currentJob = null;
let busy = false;
let ffmpegReady = false;
let failures = 0;

function message(text) {
  $("message").textContent = text || "";
  $("message").hidden = !text;
}

async function api(path, data) {
  const options =
    data === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
          body: JSON.stringify(data),
        };
  const response = await fetch(path, options);
  const payload = await response.json();
  if (!response.ok) {
    const error = new Error(
      payload.error || "تعذّر إكمال الطلب. حاول مرة أخرى.",
    );
    error.status = response.status;
    throw error;
  }
  return payload;
}

function setBusy(value) {
  busy = value;
  $("urlInput").disabled = value;
  $("extractBtn").disabled = value;
  $("downloadBtn").disabled = value || !ffmpegReady;
  $("metadata").disabled = value;
  $("subtitles").disabled = value;
  $("language").disabled = value || !$("subtitles").checked;
  document.querySelectorAll('input[name="quality"]').forEach((input) => {
    input.disabled = value;
  });
}

function duration(seconds) {
  return `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
}

function bytes(value) {
  if (!value) return "";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(3, Math.floor(Math.log(value) / Math.log(1024)));
  return `${(value / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`;
}

function bundleNote() {
  $("language").disabled = busy || !$("subtitles").checked;
  $("bundleNote").textContent =
    $("metadata").checked || $("subtitles").checked
      ? "ستحصل على ملف ZIP يضم الفيديو والمرفقات المتاحة."
      : "ستحصل على ملف فيديو MP4.";
}

function renderVideo() {
  $("videoTitle").textContent = video.title;
  $("channel").textContent = video.channel || "Dailymotion";
  $("duration").textContent = duration(video.duration);
  $("sourceLink").href = video.source_url;
  $("thumbnail").hidden = !video.thumbnail;
  if (video.thumbnail) $("thumbnail").src = video.thumbnail;
  $("qualityCount").textContent = `${video.qualities.length} جودات متاحة`;
  $("qualityGrid").replaceChildren();
  video.qualities.forEach((quality, index) => {
    const label = document.createElement("label");
    label.className = "quality-option";
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "quality";
    input.value = String(quality);
    input.checked = index === 0;
    const content = document.createElement("span");
    content.className = "quality-content";
    const number = document.createElement("span");
    number.className = "quality-number";
    number.textContent = `${quality}p`;
    const caption = document.createElement("span");
    caption.className = "quality-caption";
    caption.textContent =
      index === 0
        ? "أعلى جودة متاحة"
        : quality >= 720
          ? "عالية الوضوح"
          : "حجم أصغر";
    content.append(number, caption);
    label.append(input, content);
    $("qualityGrid").append(label);
  });
  $("language").replaceChildren(new Option("كل اللغات المتاحة", "all"));
  video.subtitles.forEach((track) => {
    const label = `${track.name} (${track.language})${track.automatic ? " — تلقائية" : ""}`;
    $("language").append(new Option(label, track.language));
  });
  $("subtitleControl").hidden = video.subtitles.length === 0;
  $("subtitles").checked = false;
  $("subtitleHint").textContent =
    `${video.subtitles.length} مسارات متاحة؛ قد تتضمن ترجمة تلقائية`;
  $("results").hidden = false;
  $("emptyState").hidden = true;
  $("jobPanel").hidden = true;
  bundleNote();
}

$("extractForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy) return;
  message("");
  setBusy(true);
  $("extractBtn").firstElementChild.textContent = "جارٍ الاستخراج…";
  $("results").hidden = true;
  try {
    const result = await api("/api/extract", {
      url: $("urlInput").value.trim(),
    });
    video = result.video;
    renderVideo();
  } catch (error) {
    message(error.message);
  } finally {
    setBusy(false);
    $("extractBtn").firstElementChild.textContent = "استخراج الفيديو";
  }
});

$("downloadBtn").addEventListener("click", async () => {
  if (!video || busy) return;
  message("");
  setBusy(true);
  try {
    const result = await api("/api/jobs", {
      url: video.source_url,
      quality: document.querySelector('input[name="quality"]:checked').value,
      metadata: $("metadata").checked,
      subtitles: $("subtitles").checked ? [$("language").value] : [],
    });
    currentJob = result.id;
    sessionStorage.setItem("dailydl-job", currentJob);
    beginProgress();
    poll();
  } catch (error) {
    setBusy(false);
    message(error.message);
  }
});

function beginProgress() {
  $("jobPanel").hidden = false;
  $("jobHeading").textContent = "جارٍ تحضير ملفك";
  $("cancelBtn").hidden = false;
  $("cancelBtn").disabled = false;
  $("cancelBtn").textContent = "إلغاء العملية";
  $("saveBtn").hidden = true;
  $("jobWarnings").hidden = true;
  $("progress").removeAttribute("value");
  $("percentage").textContent = "—";
  $("stage").textContent = "جارٍ استخراج الفيديو…";
  $("transfer").textContent = "";
  failures = 0;
}

function finish() {
  sessionStorage.removeItem("dailydl-job");
  currentJob = null;
  $("cancelBtn").hidden = true;
  setBusy(false);
}

async function poll() {
  if (!currentJob) return;
  const identifier = currentJob;
  try {
    const job = await api(`/api/jobs/${identifier}`);
    if (identifier !== currentJob) return;
    failures = 0;
    const stages = {
      extracting: "جارٍ استخراج الفيديو…",
      downloading: "جارٍ تنزيل الفيديو…",
      processing: "جارٍ تجميع الملف…",
      cancelling: "جارٍ الإلغاء…",
      complete: "الملف جاهز للحفظ",
    };
    $("stage").textContent = stages[job.stage] || "جارٍ العمل…";
    if (typeof job.percent === "number") {
      $("progress").value = job.percent;
      $("percentage").textContent = `${Math.round(job.percent)}%`;
    } else {
      $("progress").removeAttribute("value");
      $("percentage").textContent = "—";
    }
    $("transfer").textContent = [
      bytes(job.downloaded_bytes),
      job.speed ? `${bytes(job.speed)}/s` : "",
    ]
      .filter(Boolean)
      .join(" · ");
    if (job.status === "done") {
      $("jobHeading").textContent = "ملفك جاهز";
      $("saveBtn").href = `/api/jobs/${identifier}/file`;
      $("saveBtn").download = job.filename;
      $("saveBtn").hidden = false;
      $("stage").textContent = `جاهز للحفظ لمدة 15 دقيقة · ${bytes(job.size)}`;
      $("jobWarnings").textContent = (job.warnings || []).join("\n");
      $("jobWarnings").hidden = !job.warnings?.length;
      finish();
      return;
    }
    if (["error", "cancelled", "downloaded"].includes(job.status)) {
      $("jobHeading").textContent =
        job.status === "cancelled"
          ? "تم إلغاء العملية"
          : job.status === "downloaded"
            ? "تم إرسال الملف"
            : "تعذّر إكمال التحميل";
      $("stage").textContent =
        job.status === "error" ? job.error : "يمكنك بدء تحميل جديد.";
      if (job.status === "error") message(job.error);
      finish();
      return;
    }
    setTimeout(poll, 700);
  } catch (error) {
    if (identifier !== currentJob) return;
    if (error.status === 404) {
      $("jobHeading").textContent = "انتهت صلاحية العملية";
      $("stage").textContent = "ابدأ تحميلًا جديدًا للحصول على الملف.";
      message(
        "هذه العملية انتهت صلاحيتها أو انتهت الجلسة. يمكنك بدء تحميل جديد.",
      );
      finish();
      return;
    }
    failures += 1;
    if (failures >= 5) {
      message("تعذّر متابعة الحالة. أعد تحميل الصفحة لاستعادة متابعة العملية.");
      $("cancelBtn").disabled = false;
      return;
    }
    setTimeout(poll, 1500);
  }
}

$("cancelBtn").addEventListener("click", async () => {
  if (!currentJob) return;
  $("cancelBtn").disabled = true;
  $("cancelBtn").textContent = "جارٍ الإلغاء…";
  try {
    await api(`/api/jobs/${currentJob}/cancel`, {});
    if (failures >= 5) {
      failures = 0;
      poll();
    }
  } catch (error) {
    message(error.message);
    $("cancelBtn").disabled = false;
  }
});

$("saveBtn").addEventListener("click", () => {
  // Navigate directly to a streamed attachment; do not hold the whole video in a Blob.
  setTimeout(() => {
    $("saveBtn").hidden = true;
    $("stage").textContent = "تم إرسال طلب الحفظ. تابع التنزيل في متصفحك.";
  }, 0);
});
$("metadata").addEventListener("change", bundleNote);
$("subtitles").addEventListener("change", bundleNote);
$("thumbnail").addEventListener("error", () => {
  $("thumbnail").hidden = true;
});

api("/api/health")
  .then((health) => {
    ffmpegReady = health.ffmpeg && health.ffprobe;
    $("engineStatus").textContent = ffmpegReady
      ? "جاهز للاستخراج والتحميل"
      : "استخراج متاح · التحميل يحتاج FFmpeg";
    $("dependencyNotice").hidden = ffmpegReady;
    setBusy(busy);
  })
  .catch(() => {
    $("engineStatus").textContent = "تعذّر التحقق من الخادم";
  });

const savedJob = sessionStorage.getItem("dailydl-job");
if (savedJob && /^[a-f0-9]{32}$/.test(savedJob)) {
  currentJob = savedJob;
  setBusy(true);
  beginProgress();
  poll();
}
