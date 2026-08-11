import { useEffect, useState, type ReactNode } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Brain,
  Check,
  CheckCircle2,
  ChevronDown,
  CirclePlay,
  Cloud,
  Film,
  FolderOpen,
  Gauge,
  HardDrive,
  Image,
  ListFilter,
  MessageSquareText,
  MousePointer2,
  Play,
  Scissors,
  Search,
  ShieldCheck,
  Sparkles,
  Star,
  Upload,
  WandSparkles,
  X,
  type LucideIcon,
} from "lucide-react";

import { cn } from "@/lib/utils";

type TutorialPageProps = {
  gate?: boolean;
  onComplete?: (destination: "dashboard" | "onboarding") => void;
};

type DemoKind = "overview" | "workspace" | "process" | "clip-room" | "gallery" | "editor" | "taste" | "account" | "launch";

type TutorialStep = {
  nav: string;
  eyebrow: string;
  title: string;
  description: string;
  icon: LucideIcon;
  demo: DemoKind;
  task: string;
  outcome: string;
};

const STEPS: TutorialStep[] = [
  {
    nav: "The workflow",
    eyebrow: "Welcome to InstaClip",
    title: "One stream in. Reviewable clips out.",
    description: "InstaClip is a local-first creative workstation. It watches the full story, proposes moments, learns from your decisions, and gives you a real timeline for the final cut.",
    icon: Sparkles,
    demo: "overview",
    task: "Understand the five-stage workflow before processing your first VOD.",
    outcome: "You stay the editor. AI creates a first pass, not an automatic final answer.",
  },
  {
    nav: "Your workspace",
    eyebrow: "Core workflow 1 of 7",
    title: "Choose a video from this computer",
    description: "Your source files do not upload to a shared media library. Each device has its own VODs, clips, imports, editor projects, and cache.",
    icon: FolderOpen,
    demo: "workspace",
    task: "Use Pick a file on Process VOD, or drag a supported video into the drop zone.",
    outcome: "The app remembers the project locally and can resume long jobs after a restart.",
  },
  {
    nav: "Process a VOD",
    eyebrow: "Core workflow 2 of 7",
    title: "Let the pipeline watch the stream once",
    description: "The first run creates a timestamped transcript, identifies story context, scores candidate moments, verifies boundaries, and cuts the strongest options.",
    icon: WandSparkles,
    demo: "process",
    task: "Press Run once, then follow the active job instead of starting the same VOD again.",
    outcome: "A long stream can take time, but checkpoints protect completed transcription work.",
  },
  {
    nav: "Review candidates",
    eyebrow: "Core workflow 3 of 7",
    title: "Teach the difference between a moment and a usable clip",
    description: "Clip Room is the inbox for proposed moments. Watch the preview, inspect why it was selected, then make the decision that best describes the result.",
    icon: MessageSquareText,
    demo: "clip-room",
    task: "Use Good, Boundary fix, or Not a clip accurately. These choices teach different lessons.",
    outcome: "A bad ending does not poison a good idea, and random filler does not become taste evidence.",
  },
  {
    nav: "Find your work",
    eyebrow: "Core workflow 4 of 7",
    title: "Use Gallery as your searchable clip library",
    description: "Gallery holds generated, imported, reviewed, and edited clips. Filters and sorting follow you into autoplay so large batches stay manageable.",
    icon: Image,
    demo: "gallery",
    task: "Start with a preset such as Top candidates or Boundary fixes, then narrow by stream, score, duration, and tags.",
    outcome: "You can move through hundreds of clips without losing the review order you chose.",
  },
  {
    nav: "Edit and export",
    eyebrow: "Core workflow 5 of 7",
    title: "Finish the idea on a multi-track timeline",
    description: "Editor V2 combines live preview with visual clip filmstrips, waveforms, captions, transitions, overlays, imported media, and layered sound effects.",
    icon: Scissors,
    demo: "editor",
    task: "Zoom in, drag clip edges, split at the playhead, and preview the complete cut before rendering.",
    outcome: "Rendering creates a new MP4. Your original source and project history remain intact.",
  },
  {
    nav: "Teach your taste",
    eyebrow: "Core workflow 6 of 7",
    title: "Calibrate what good means for your channel",
    description: "A general model cannot know your timing, humor, context tolerance, or preferred clip length. Taste Setup turns your examples and corrections into an editable profile.",
    icon: Brain,
    demo: "taste",
    task: "Choose a foundation, add a few explained good and bad examples, then review one calibration VOD.",
    outcome: "Future selections adapt while every learned preference stays visible and editable.",
  },
  {
    nav: "Account and quota",
    eyebrow: "Core workflow 7 of 7",
    title: "Know what is local and what follows your account",
    description: "Your video files never leave this computer. To pick clips, the app sends the transcript text (what was said) to our AI provider — the video itself is never uploaded. Your account carries sign-in, AI allowance, usage history, and device sessions.",
    icon: Gauge,
    demo: "account",
    task: "Check Account & Usage before a large batch and sign out before handing a device to someone else.",
    outcome: "Video stays on your machine; only transcript text is sent for AI clip selection. Usage is isolated per tester.",
  },
  {
    nav: "First project",
    eyebrow: "Ready to create",
    title: "Complete one small project end to end",
    description: "The first goal is not maximum output. It is learning the loop: process, review, correct, edit, and export one result you understand.",
    icon: Film,
    demo: "launch",
    task: "Use a shorter VOD first, review at least five candidates, fix one boundary, and render one clip.",
    outcome: "After that first loop, run Taste Setup and move to larger streams with confidence.",
  },
];

export function TutorialPage({ gate = false, onComplete }: TutorialPageProps) {
  const [index, setIndex] = useState(0);
  const step = STEPS[index];
  const StepIcon = step.icon;
  const last = index === STEPS.length - 1;

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "ArrowRight" && !last) setIndex((value) => Math.min(STEPS.length - 1, value + 1));
      if (event.key === "ArrowLeft" && index > 0) setIndex((value) => Math.max(0, value - 1));
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [index, last]);

  function finish(destination: "dashboard" | "onboarding") {
    onComplete?.(destination);
  }

  return <div className={cn("relative min-h-full overflow-hidden bg-[#080b10] text-slate-100", gate && "h-screen")}>
    <div className="pointer-events-none absolute inset-0 opacity-40" style={{ backgroundImage: "linear-gradient(rgba(255,255,255,.025) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.025) 1px, transparent 1px)", backgroundSize: "44px 44px" }} />
    <div className="pointer-events-none absolute -left-32 top-20 h-80 w-80 rounded-full bg-cyan-300/10 blur-[110px]" />
    <div className="pointer-events-none absolute right-0 top-0 h-96 w-96 rounded-full bg-amber-300/[0.07] blur-[130px]" />

    <div className="relative mx-auto flex min-h-full w-full max-w-[1500px] flex-col px-4 py-4 sm:px-6 lg:px-8">
      <header className="flex shrink-0 items-center justify-between gap-4 border-b border-white/8 pb-4">
        <div className="flex items-center gap-3"><div className="grid h-9 w-9 place-items-center rounded-xl bg-cyan-200 font-black text-slate-950">IC</div><div><div className="text-xs font-black tracking-tight text-white">InstaClip guided setup</div><div className="text-[9px] uppercase tracking-[0.18em] text-slate-600">Learn the complete workflow</div></div></div>
        <div className="hidden flex-1 items-center justify-center gap-1.5 px-8 lg:flex">{STEPS.map((item, itemIndex) => <button key={item.nav} type="button" onClick={() => setIndex(itemIndex)} className={cn("h-1.5 rounded-full transition-all", itemIndex === index ? "w-10 bg-cyan-200" : itemIndex < index ? "w-5 bg-cyan-200/35" : "w-5 bg-white/10")} aria-label={`Open ${item.nav}`} />)}</div>
        <button type="button" onClick={() => finish("dashboard")} className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-black/20 px-4 py-2 text-xs font-semibold text-slate-400 hover:border-white/20 hover:text-white"><X className="h-3.5 w-3.5" /> {gate ? "Skip for now" : "Close"}</button>
      </header>

      <main className="grid min-h-0 flex-1 gap-5 py-5 lg:grid-cols-[minmax(300px,0.68fr)_minmax(620px,1.32fr)] lg:gap-7">
        <section className="flex min-h-0 flex-col justify-center">
          <div className="flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.22em] text-cyan-200/70"><StepIcon className="h-4 w-4" /> {step.eyebrow}</div>
          <h1 className="mt-4 max-w-xl font-display text-4xl font-semibold leading-[1.02] tracking-[-0.045em] text-white sm:text-5xl">{step.title}</h1>
          <p className="mt-5 max-w-xl text-sm leading-6 text-slate-400">{step.description}</p>
          <div className="mt-7 space-y-2">
            <Guidance icon={MousePointer2} label="What you do" text={step.task} tone="cyan" />
            <Guidance icon={CheckCircle2} label="What you get" text={step.outcome} tone="emerald" />
          </div>
          <p className="mt-5 text-[10px] text-slate-600">Tip: use the left and right arrow keys to move through this guide.</p>
        </section>

        <section className="min-h-[450px] overflow-hidden rounded-3xl border border-white/10 bg-[#0d1218]/95 p-3 shadow-2xl shadow-black/50 backdrop-blur-xl sm:p-4">
          <ProductDemo kind={step.demo} />
        </section>
      </main>

      <footer className="flex shrink-0 flex-col-reverse gap-3 border-t border-white/8 pt-4 sm:flex-row sm:items-center sm:justify-between">
        <div><div className="text-[10px] font-bold text-slate-400">{index + 1} of {STEPS.length}: {step.nav}</div><div className="mt-1 text-[9px] text-slate-600">Progress is saved when you finish or skip.</div></div>
        <div className="flex justify-end gap-2">
          <button type="button" disabled={index === 0} onClick={() => setIndex((value) => Math.max(0, value - 1))} className="inline-flex items-center gap-2 rounded-xl border border-white/10 px-4 py-2.5 text-xs font-bold text-slate-300 disabled:opacity-25"><ArrowLeft className="h-3.5 w-3.5" /> Back</button>
          {last ? <>
            <button type="button" onClick={() => finish("dashboard")} className="rounded-xl border border-white/10 px-4 py-2.5 text-xs font-bold text-slate-300">Open Process VOD</button>
            <button type="button" onClick={() => finish("onboarding")} className="inline-flex items-center gap-2 rounded-xl bg-cyan-200 px-5 py-2.5 text-xs font-black text-slate-950"><Brain className="h-4 w-4" /> Set up my taste</button>
          </> : <button type="button" onClick={() => setIndex((value) => Math.min(STEPS.length - 1, value + 1))} className="inline-flex items-center gap-2 rounded-xl bg-cyan-200 px-5 py-2.5 text-xs font-black text-slate-950">Next: {STEPS[index + 1].nav} <ArrowRight className="h-4 w-4" /></button>}
        </div>
      </footer>
    </div>
  </div>;
}

function Guidance({ icon: Icon, label, text, tone }: { icon: LucideIcon; label: string; text: string; tone: "cyan" | "emerald" }) {
  return <div className={cn("flex gap-3 rounded-xl border p-3", tone === "cyan" ? "border-cyan-200/15 bg-cyan-200/[0.04]" : "border-emerald-300/15 bg-emerald-300/[0.04]")}><Icon className={cn("mt-0.5 h-4 w-4 shrink-0", tone === "cyan" ? "text-cyan-200" : "text-emerald-300")} /><div><div className="text-[9px] font-black uppercase tracking-[0.16em] text-slate-500">{label}</div><p className="mt-1 text-xs leading-5 text-slate-300">{text}</p></div></div>;
}

function ProductDemo({ kind }: { kind: DemoKind }) {
  return <div className="flex h-full min-h-[420px] flex-col overflow-hidden rounded-2xl border border-white/8 bg-[#090d12]">
    <div className="flex h-10 shrink-0 items-center gap-2 border-b border-white/8 bg-[#11171e] px-3"><span className="h-2.5 w-2.5 rounded-full bg-rose-400/70" /><span className="h-2.5 w-2.5 rounded-full bg-amber-300/70" /><span className="h-2.5 w-2.5 rounded-full bg-emerald-300/70" /><span className="ml-2 text-[9px] font-bold uppercase tracking-[0.18em] text-slate-600">InstaClip workspace preview</span></div>
    <div className="min-h-0 flex-1 p-3 sm:p-4">{{
      overview: <OverviewDemo />,
      workspace: <WorkspaceDemo />,
      process: <ProcessDemo />,
      "clip-room": <ClipRoomDemo />,
      gallery: <GalleryDemo />,
      editor: <EditorDemo />,
      taste: <TasteDemo />,
      account: <AccountDemo />,
      launch: <LaunchDemo />,
    }[kind]}</div>
  </div>;
}

function ScreenHeader({ icon: Icon, title, detail, action }: { icon: LucideIcon; title: string; detail: string; action?: ReactNode }) {
  return <div className="flex items-center justify-between gap-3"><div className="flex items-center gap-2"><div className="grid h-8 w-8 place-items-center rounded-lg border border-white/8 bg-white/[0.04]"><Icon className="h-4 w-4 text-cyan-200" /></div><div><div className="text-xs font-bold text-white">{title}</div><div className="text-[8px] text-slate-600">{detail}</div></div></div>{action}</div>;
}

function OverviewDemo() {
  const stages = [
    [Upload, "1. Add VOD", "Choose a local stream"],
    [WandSparkles, "2. Process", "Transcript and detect"],
    [MessageSquareText, "3. Review", "Approve or correct"],
    [Scissors, "4. Edit", "Polish the timeline"],
    [Film, "5. Export", "Render a new MP4"],
  ] as const;
  return <div className="flex h-full flex-col"><ScreenHeader icon={Sparkles} title="Your clip production loop" detail="Every stage is reviewable and non-destructive" /><div className="mt-6 grid flex-1 content-center gap-2 sm:grid-cols-5">{stages.map(([Icon, title, detail], index) => <div key={title} className="relative rounded-xl border border-white/8 bg-white/[0.025] p-3 text-center"><div className="mx-auto grid h-10 w-10 place-items-center rounded-xl bg-cyan-200/[0.08]"><Icon className="h-5 w-5 text-cyan-200" /></div><div className="mt-3 text-[10px] font-bold text-white">{title}</div><div className="mt-1 text-[8px] leading-3 text-slate-600">{detail}</div>{index < stages.length - 1 && <ArrowRight className="absolute -right-3 top-1/2 z-10 hidden h-4 w-4 text-slate-700 sm:block" />}</div>)}</div><div className="mt-5 flex items-center gap-3 rounded-xl border border-amber-300/15 bg-amber-300/[0.04] p-3"><ShieldCheck className="h-5 w-5 text-amber-200" /><div><div className="text-[9px] font-bold text-amber-100">Human approval is part of the product</div><div className="mt-0.5 text-[8px] text-slate-500">Nothing becomes a finished creative decision until you review it.</div></div></div></div>;
}

function WorkspaceDemo() {
  return <div className="flex h-full flex-col"><ScreenHeader icon={FolderOpen} title="Process VOD" detail="Start a resumable clipping job" /><div className="mt-4 grid flex-1 gap-3 md:grid-cols-[1.2fr_.8fr]"><div className="grid place-items-center rounded-2xl border border-dashed border-cyan-200/25 bg-cyan-200/[0.035] p-6 text-center"><div><div className="mx-auto grid h-14 w-14 place-items-center rounded-2xl border border-cyan-200/15 bg-cyan-200/[0.06]"><Upload className="h-6 w-6 text-cyan-200" /></div><div className="mt-4 text-sm font-bold text-white">Drop a stream recording here</div><div className="mt-2 text-[9px] text-slate-500">MP4, MKV, MOV, AVI, FLV, or WebM</div><button type="button" className="mt-4 inline-flex items-center gap-2 rounded-lg bg-cyan-200 px-4 py-2 text-[9px] font-black text-slate-950"><FolderOpen className="h-3.5 w-3.5" /> Pick a file</button></div></div><div className="space-y-2"><StorageCard icon={HardDrive} title="Stays on this PC" lines={["Source VOD", "Generated clips", "Editor projects", "Imported media"]} /><StorageCard icon={Cloud} title="Follows your account" lines={["Sign-in", "AI allowance", "Usage history", "Device sessions"]} /></div></div></div>;
}

function StorageCard({ icon: Icon, title, lines }: { icon: LucideIcon; title: string; lines: string[] }) {
  return <div className="rounded-xl border border-white/8 bg-white/[0.025] p-3"><div className="flex items-center gap-2 text-[9px] font-bold text-slate-300"><Icon className="h-4 w-4 text-cyan-200" />{title}</div><div className="mt-2 space-y-1">{lines.map((line) => <div key={line} className="flex items-center gap-2 text-[8px] text-slate-600"><Check className="h-3 w-3 text-emerald-300/70" />{line}</div>)}</div></div>;
}

function ProcessDemo() {
  const stages = [["Reading media", "complete", "Video and audio streams verified"], ["Transcribing", "active", "42:18 of 1:03:40 checkpointed"], ["Understanding story", "waiting", "Format, speakers, events, and payoffs"], ["Selecting clips", "waiting", "Score and boundary verification"], ["Cutting files", "waiting", "Only after selection finishes"]] as const;
  return <div className="flex h-full flex-col"><ScreenHeader icon={WandSparkles} title="Active job" detail="rocomamas-challenge.mp4" action={<span className="rounded-full border border-amber-300/20 bg-amber-300/[0.06] px-2 py-1 text-[8px] font-bold text-amber-200">RUNNING</span>} /><div className="mt-4 rounded-xl border border-white/8 bg-black/20 p-3"><div className="flex justify-between text-[8px] text-slate-500"><span>Overall progress</span><span>66%</span></div><div className="mt-2 h-2 overflow-hidden rounded-full bg-white/5"><div className="h-full w-2/3 rounded-full bg-gradient-to-r from-cyan-300 to-emerald-300" /></div></div><div className="mt-3 space-y-1.5">{stages.map(([title, status, detail], index) => <div key={title} className={cn("flex items-center gap-3 rounded-xl border p-3", status === "active" ? "border-cyan-200/25 bg-cyan-200/[0.05]" : "border-white/6 bg-white/[0.02]")}><div className={cn("grid h-6 w-6 place-items-center rounded-full text-[8px] font-black", status === "complete" ? "bg-emerald-300 text-slate-950" : status === "active" ? "bg-cyan-200 text-slate-950" : "bg-white/5 text-slate-600")}>{status === "complete" ? <Check className="h-3.5 w-3.5" /> : index + 1}</div><div className="min-w-0 flex-1"><div className="text-[9px] font-bold text-slate-300">{title}</div><div className="mt-0.5 truncate text-[8px] text-slate-600">{detail}</div></div>{status === "active" && <div className="h-3 w-3 animate-spin rounded-full border-2 border-cyan-200 border-t-transparent" />}</div>)}</div></div>;
}

function ClipRoomDemo() {
  const [decision, setDecision] = useState("boundary");
  const explanations: Record<string, string> = { good: "Positive taste signal: this moment and its boundaries work.", boundary: "The idea stays positive; only the cut timing needs correction.", null: "Removed as filler or duplicate without teaching negative taste." };
  return <div className="flex h-full flex-col"><ScreenHeader icon={MessageSquareText} title="Clip Room" detail="Candidate 18 of 146" action={<button type="button" className="flex items-center gap-1 rounded border border-white/10 px-2 py-1 text-[8px] text-slate-400"><ListFilter className="h-3 w-3" /> Top candidates</button>} /><div className="mt-3 grid min-h-0 flex-1 gap-3 md:grid-cols-[1.15fr_.85fr]"><div className="relative overflow-hidden rounded-xl border border-white/8 bg-gradient-to-br from-orange-900/50 via-slate-900 to-cyan-900/40"><div className="absolute inset-0 grid place-items-center"><button type="button" className="grid h-12 w-12 place-items-center rounded-full border border-white/20 bg-black/50"><Play className="ml-0.5 h-5 w-5 text-white" /></button></div><div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black via-black/60 to-transparent p-3"><div className="text-[10px] font-bold text-white">The challenge finally hits back</div><div className="mt-1 text-[8px] text-slate-400">01:24:16 - 01:24:48</div></div></div><div className="flex flex-col gap-2"><div className="rounded-xl border border-white/8 bg-white/[0.025] p-3"><div className="flex items-center justify-between"><span className="text-[8px] uppercase tracking-wide text-slate-600">Why this pick</span><span className="text-lg font-black text-emerald-300">91</span></div><p className="mt-2 text-[8px] leading-4 text-slate-400">Clear escalation, strong reaction, and a complete payoff line.</p></div><div className="grid grid-cols-3 gap-1">{[["good", "Good"], ["boundary", "Boundary fix"], ["null", "Not a clip"]].map(([value, label]) => <button key={value} type="button" onClick={() => setDecision(value)} className={cn("rounded-lg border px-1 py-2 text-[8px] font-bold", decision === value ? "border-cyan-200/40 bg-cyan-200/[0.09] text-cyan-100" : "border-white/8 text-slate-600")}>{label}</button>)}</div><div className="rounded-xl border border-cyan-200/15 bg-cyan-200/[0.04] p-3 text-[8px] leading-4 text-cyan-100/70">{explanations[decision]}</div></div></div></div>;
}

function GalleryDemo() {
  const cards = [["91", "Challenge payoff", "Ready"], ["86", "Ice starts eating", "Boundary"], ["82", "Bathroom reaction", "Ready"], ["74", "Opening setup", "Reviewed"]];
  return <div className="flex h-full flex-col"><ScreenHeader icon={Image} title="Gallery" detail="Search, sort, autoplay, and organize every clip" /><div className="mt-3 flex flex-wrap gap-1.5"><div className="flex min-w-40 flex-1 items-center gap-2 rounded-lg border border-white/8 bg-black/20 px-2 py-2"><Search className="h-3 w-3 text-slate-600" /><span className="text-[8px] text-slate-600">Search transcript or filename</span></div>{["Stream: All", "Score: 70+", "Sort: Highest", "Autoplay: On"].map((filter) => <button key={filter} type="button" className="flex items-center gap-1 rounded-lg border border-white/8 bg-white/[0.025] px-2 py-2 text-[8px] text-slate-400">{filter}<ChevronDown className="h-3 w-3" /></button>)}</div><div className="mt-3 grid flex-1 grid-cols-2 gap-2 lg:grid-cols-4">{cards.map(([score, title, state], index) => <div key={title} className="overflow-hidden rounded-xl border border-white/8 bg-white/[0.025]"><div className={cn("relative h-28", ["bg-gradient-to-br from-orange-900/60 to-slate-900", "bg-gradient-to-br from-blue-900/60 to-slate-900", "bg-gradient-to-br from-rose-900/60 to-slate-900", "bg-gradient-to-br from-emerald-900/50 to-slate-900"][index])}><span className="absolute right-2 top-2 rounded bg-black/60 px-1.5 py-1 text-[8px] font-black text-emerald-300">{score}</span><CirclePlay className="absolute left-2 bottom-2 h-5 w-5 text-white/80" /></div><div className="p-2"><div className="truncate text-[9px] font-bold text-slate-200">{title}</div><div className="mt-1 text-[8px] text-slate-600">{state}</div></div></div>)}</div><div className="mt-3 rounded-lg border border-amber-300/15 bg-amber-300/[0.04] p-2 text-[8px] text-amber-100/70">With autoplay on, your review decision advances to the next clip inside the current filter and sort order.</div></div>;
}

function EditorDemo() {
  return <div className="flex h-full flex-col"><ScreenHeader icon={Scissors} title="Editor V2" detail="Preview, layer, trim, and export" action={<button type="button" className="rounded-lg bg-cyan-200 px-3 py-1.5 text-[8px] font-black text-slate-950">Render MP4</button>} /><div className="mt-3 grid min-h-0 flex-1 grid-rows-[1fr_auto] gap-2"><div className="grid min-h-0 gap-2 md:grid-cols-[140px_1fr_150px]"><div className="rounded-lg border border-white/8 bg-white/[0.02] p-2"><div className="text-[8px] font-bold uppercase text-slate-600">Project media</div><div className="mt-2 grid grid-cols-2 gap-1">{["Source", "Boom", "Photo", "Caption"].map((item, index) => <div key={item} className="rounded border border-white/8 bg-black/30 p-1"><div className={cn("h-10 rounded", index === 0 ? "bg-gradient-to-br from-orange-800 to-slate-900" : "bg-white/5")} /><div className="mt-1 truncate text-[7px] text-slate-500">{item}</div></div>)}</div></div><div className="relative grid place-items-center overflow-hidden rounded-lg border border-white/8 bg-black"><div className="aspect-video w-4/5 bg-gradient-to-br from-orange-900/70 via-slate-900 to-cyan-900/40" /><button type="button" className="absolute grid h-10 w-10 place-items-center rounded-full bg-black/60"><Play className="h-4 w-4 text-white" /></button></div><div className="rounded-lg border border-white/8 bg-white/[0.02] p-2"><div className="text-[8px] font-bold uppercase text-slate-600">Inspector</div>{["Position", "Crop", "Speed", "Volume", "Transition"].map((item) => <div key={item} className="mt-2 flex items-center justify-between border-b border-white/5 pb-1.5 text-[8px] text-slate-400"><span>{item}</span><ChevronDown className="h-3 w-3 text-slate-700" /></div>)}</div></div><MockTimeline /></div></div>;
}

function MockTimeline() {
  return <div className="overflow-hidden rounded-lg border border-white/8 bg-[#0b1015]"><div className="flex h-6 items-center border-b border-white/8 px-2"><Scissors className="h-3 w-3 text-slate-500" /><span className="ml-2 text-[7px] uppercase tracking-wide text-slate-600">Timeline with visual filmstrips</span></div><div className="relative p-2 pl-12"><div className="absolute bottom-0 left-[42%] top-0 z-20 w-px bg-rose-400"><div className="-ml-1 h-2 w-2 bg-rose-400" /></div><div className="absolute left-2 top-3 text-[7px] font-black text-cyan-300">V1</div><div className="flex h-10 gap-0.5 overflow-hidden rounded border border-cyan-300/30">{Array.from({ length: 9 }, (_, index) => <div key={index} className={cn("min-w-12 flex-1 bg-gradient-to-br", index % 3 === 0 ? "from-orange-800 to-slate-900" : index % 3 === 1 ? "from-cyan-900 to-slate-900" : "from-rose-900 to-slate-900")} />)}</div><div className="relative mt-1.5 h-7 overflow-hidden rounded border border-emerald-300/25 bg-emerald-400/10"><svg viewBox="0 0 600 40" className="h-full w-full text-emerald-300/50" preserveAspectRatio="none"><path d="M0 20 L10 5 20 34 30 12 40 28 50 4 60 36 70 16 80 24 90 8 100 32 110 14 120 26 130 2 140 38 150 18 160 22 170 6 180 34 190 10 200 30 210 4 220 36 230 17 240 23 250 8 260 32 270 12 280 28 290 5 300 35 310 15 320 25 330 7 340 33 350 11 360 29 370 3 380 37 390 18 400 22 410 6 420 34 430 13 440 27 450 4 460 36 470 16 480 24 490 8 500 32 510 10 520 30 530 5 540 35 550 14 560 26 570 7 580 33 590 12 600 20" fill="none" stroke="currentColor" strokeWidth="2" /></svg></div></div></div>;
}

function TasteDemo() {
  return <div className="flex h-full flex-col"><ScreenHeader icon={Brain} title="Taste Setup" detail="Build a profile from decisions you can inspect" /><div className="mt-4 grid grid-cols-3 gap-2">{[["General", "Balanced hooks and payoffs"], ["Creator reference", "Start from an example style"], ["Personalized", "Build from your own clips"]].map(([title, detail], index) => <button key={title} type="button" className={cn("rounded-xl border p-3 text-left", index === 2 ? "border-cyan-200/35 bg-cyan-200/[0.07]" : "border-white/8 bg-white/[0.02]")}><div className="flex items-center justify-between text-[9px] font-bold text-white">{title}{index === 2 && <Check className="h-3.5 w-3.5 text-cyan-200" />}</div><div className="mt-2 text-[8px] leading-3 text-slate-600">{detail}</div></button>)}</div><div className="mt-3 grid flex-1 gap-2 md:grid-cols-2"><div className="rounded-xl border border-emerald-300/15 bg-emerald-300/[0.03] p-3"><div className="flex items-center gap-2 text-[9px] font-bold text-emerald-200"><Star className="h-3.5 w-3.5" /> Good example</div><div className="mt-3 h-20 rounded-lg bg-gradient-to-br from-orange-900/50 to-slate-900" /><div className="mt-2 rounded border border-white/8 bg-black/20 p-2 text-[8px] text-slate-500">Why? "Fast setup, reaction lands, no dead air."</div></div><div className="rounded-xl border border-rose-300/15 bg-rose-300/[0.03] p-3"><div className="flex items-center gap-2 text-[9px] font-bold text-rose-200"><X className="h-3.5 w-3.5" /> Bad example</div><div className="mt-3 h-20 rounded-lg bg-gradient-to-br from-slate-700/40 to-slate-900" /><div className="mt-2 rounded border border-white/8 bg-black/20 p-2 text-[8px] text-slate-500">Why? "No context and the punchline is cut off."</div></div></div><div className="mt-3 text-[8px] text-slate-600">Specific explanations teach more than an unexplained thumbs up or down.</div></div>;
}

function AccountDemo() {
  return <div className="flex h-full flex-col"><ScreenHeader icon={Gauge} title="Account & Usage" detail="Allowance, activity, and approved devices" /><div className="mt-4 grid gap-3 md:grid-cols-[1.1fr_.9fr]"><div className="rounded-2xl border border-white/8 bg-white/[0.025] p-4"><div className="flex items-end justify-between"><div><div className="text-[8px] uppercase tracking-wide text-slate-600">AI allowance remaining</div><div className="mt-2 text-3xl font-black text-white">78%</div></div><Gauge className="h-10 w-10 text-cyan-200/60" /></div><div className="mt-4 h-2 overflow-hidden rounded-full bg-white/5"><div className="h-full w-[78%] rounded-full bg-gradient-to-r from-cyan-300 to-emerald-300" /></div><div className="mt-3 grid grid-cols-3 gap-2">{[["Used", "22%"], ["Jobs", "1 active"], ["Reset", "6 days"]].map(([label, value]) => <div key={label} className="rounded-lg bg-black/20 p-2"><div className="text-[7px] uppercase text-slate-700">{label}</div><div className="mt-1 text-[9px] font-bold text-slate-300">{value}</div></div>)}</div></div><div className="space-y-2"><StorageCard icon={Cloud} title="Cloud account data" lines={["Allowance and usage", "Approved devices", "Sign-in sessions"]} /><StorageCard icon={HardDrive} title="Local workspace data" lines={["VODs and clips", "Taste profile", "Editor projects"]} /></div></div><div className="mt-3 rounded-xl border border-white/8 bg-black/20 p-3"><div className="text-[8px] font-bold text-slate-400">Approved devices</div><div className="mt-2 flex items-center justify-between rounded-lg border border-white/6 p-2"><div><div className="text-[8px] text-slate-300">Windows PC</div><div className="text-[7px] text-slate-700">Active now</div></div><button type="button" className="rounded border border-rose-300/15 px-2 py-1 text-[7px] text-rose-200">Revoke</button></div></div></div>;
}

function LaunchDemo() {
  const checks = [["Pick a short practice VOD", "5-20 minutes is enough"], ["Wait for one complete job", "Do not start duplicates"], ["Review five candidates", "Use the correct feedback type"], ["Fix one clip boundary", "Practice trim and split"], ["Render one MP4", "Watch the complete export"], ["Set up your taste", "Use explained examples"]];
  return <div className="flex h-full flex-col"><ScreenHeader icon={Film} title="Your first successful project" detail="A guided 20-minute product check" /><div className="mt-4 grid flex-1 content-center gap-2 md:grid-cols-2">{checks.map(([title, detail], index) => <div key={title} className="flex items-center gap-3 rounded-xl border border-white/8 bg-white/[0.025] p-3"><div className={cn("grid h-8 w-8 shrink-0 place-items-center rounded-full text-[9px] font-black", index === 0 ? "bg-cyan-200 text-slate-950" : "bg-white/5 text-slate-500")}>{index + 1}</div><div><div className="text-[9px] font-bold text-slate-200">{title}</div><div className="mt-1 text-[8px] text-slate-600">{detail}</div></div></div>)}</div><div className="mt-4 flex items-center gap-3 rounded-xl border border-emerald-300/20 bg-emerald-300/[0.05] p-4"><CheckCircle2 className="h-6 w-6 text-emerald-300" /><div><div className="text-[10px] font-bold text-emerald-100">Success means you understand every stage</div><div className="mt-1 text-[8px] text-slate-500">Scale to full streams only after one review and export loop feels clear.</div></div></div></div>;
}
