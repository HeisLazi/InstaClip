import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { CommandBar } from "@/components/CommandBar";
import { LogDrawer } from "@/components/LogDrawer";
import { Sidebar } from "@/components/Sidebar";
import { StatusBar } from "@/components/StatusBar";
import { api } from "@/api/client";
import { IS_CLIPPER, type PageKey } from "@/nav";

import { DashboardPage } from "@/pages/DashboardPage";
import { GalleryPage } from "@/pages/GalleryPage";
import { ClipRoomPage } from "@/pages/ClipRoomPage";
import { EditorPage } from "@/pages/EditorPage";
import { ProfilePage } from "@/pages/ProfilePage";
import { LanguageStudioPage } from "@/pages/LanguageStudioPage";
import { PreferencesPage } from "@/pages/PreferencesPage";
import { AccountPage } from "@/pages/AccountPage";
import { OnboardingPage } from "@/pages/OnboardingPage";
import { TutorialPage } from "@/pages/TutorialPage";

const TUTORIAL_VERSION = "v2";
const CLIPPER_ALLOWED_PAGES = new Set<PageKey>([
  "dashboard",
  "gallery",
  "clip-room",
  "editor",
  "tutorial",
  "onboarding",
  "profile",
  "language",
  "account",
  "preferences",
]);

function tutorialKey() {
  return `instaclip:tutorial:${TUTORIAL_VERSION}:local-tester`;
}

function tutorialComplete() {
  return localStorage.getItem(tutorialKey()) === "complete";
}

export function App() {
  const [current, setCurrent] = useState<PageKey>("dashboard");
  const [collapsed, setCollapsed] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [cmdOpen, setCmdOpen]     = useState(false);
  const [tutorialReady, setTutorialReady] = useState(!IS_CLIPPER);
  const [tutorialRequired, setTutorialRequired] = useState(false);
  const workspaceRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (IS_CLIPPER && !CLIPPER_ALLOWED_PAGES.has(current)) {
      setCurrent("dashboard");
    }
  }, [current]);

  useEffect(() => {
    if (!IS_CLIPPER) return;
    setTutorialRequired(!tutorialComplete());
    setTutorialReady(true);
  }, []);

  useEffect(() => {
    workspaceRef.current?.scrollTo({ top: 0, left: 0 });
  }, [current]);

  const { data: jobs } = useQuery({
    queryKey: ["jobs"],
    queryFn:  api.pipeline.jobs,
    refetchInterval: 3000,
  });
  const activeJobs = (jobs ?? []).filter((j) => j.status === "running").length;

  // Global hotkeys:
  //   Ctrl+K (or Cmd+K) — open the command bar
  //   Ctrl+/            — toggle the log drawer
  //   Esc               — close whatever's on top
  useEffect(() => {
    function handler(e: KeyboardEvent) {
      const mod = e.ctrlKey || e.metaKey;
      if (mod && (e.key === "k" || e.key === "K")) {
        e.preventDefault();
        setCmdOpen((v) => !v);
        return;
      }
      if (mod && e.key === "/") {
        e.preventDefault();
        setDrawerOpen((v) => !v);
        return;
      }
      if (e.key === "Escape") {
        if (cmdOpen) setCmdOpen(false);
        else if (drawerOpen) setDrawerOpen(false);
      }
    }
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [drawerOpen, cmdOpen]);

  if (IS_CLIPPER && !tutorialReady) return <div className="app-shell grid h-screen place-items-center text-sm text-muted-foreground">Preparing your workspace...</div>;
  if (IS_CLIPPER && tutorialRequired) return <TutorialPage gate onComplete={(destination) => {
    localStorage.setItem(tutorialKey(), "complete");
    setTutorialRequired(false);
    setCurrent(destination);
  }} />;

  return (
    <div className="app-shell h-screen w-screen flex flex-col text-foreground overflow-hidden">
      <div className="flex flex-1 overflow-hidden">
        <Sidebar
          current={current}
          onSelect={setCurrent}
          collapsed={collapsed}
          onToggle={() => setCollapsed((v) => !v)}
        />

        <main ref={workspaceRef} className="workspace-pane flex-1 overflow-y-auto">
          {current === "dashboard"   && <DashboardPage onNavigate={setCurrent} />}
          {current === "gallery"     && <GalleryPage />}
          {current === "clip-room"   && <ClipRoomPage />}
          {current === "editor"      && <EditorPage />}
          {current === "profile"     && <ProfilePage />}
          {current === "language"    && <LanguageStudioPage />}
          {current === "preferences" && <PreferencesPage />}
          {current === "onboarding" && <OnboardingPage />}
          {current === "tutorial" && <TutorialPage onComplete={setCurrent} />}
          {current === "account" && <AccountPage />}
        </main>
      </div>

      <LogDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />
      <StatusBar
        drawerOpen={drawerOpen}
        onToggleDrawer={() => setDrawerOpen((v) => !v)}
        activeJobs={activeJobs}
      />
      <CommandBar
        open={cmdOpen}
        onClose={() => setCmdOpen(false)}
        onNavigate={setCurrent}
      />
    </div>
  );
}
