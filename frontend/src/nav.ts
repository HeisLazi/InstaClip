/**
 * Sidebar taxonomy from the UI redesign doc:
 *   Workspace  — daily tasks (Dashboard merges Run + Status, Gallery = Clips)
 *   AI Studio  — heavier configuration of the ML pipeline
 *   Settings   — one-time setup (integrations + global prefs)
 */

import {
  BarChart3,
  Box,
  Brain,
  BookOpenCheck,
  Database,
  Cpu,
  Image,
  LayoutDashboard,
  MessagesSquare,
  Mic2,
  Languages,
  Plug,
  UserRound,
  ListChecks,
  Scissors,
  RadioTower,
  Settings as SettingsIcon,
  Sparkles,
  Wand2,
  Youtube,
  type LucideIcon,
} from "lucide-react";

export type PageKey =
  | "dashboard"
  | "gallery"
  | "clip-room"
  | "editor"
  | "profile"
  | "language"
  | "preferences"
  | "onboarding"
  | "tutorial"
  | "account";

export interface NavSection {
  label: string;
  items: NavItem[];
}

export interface NavItem {
  key: PageKey;
  label: string;
  icon: LucideIcon;
  hint?: string;
}

const CLIPPER_NAV: NavSection[] = [
  {
    label: "Clipper",
    items: [
      { key: "dashboard", label: "Process VOD", icon: LayoutDashboard, hint: "Run the resumable clip pipeline" },
      { key: "clip-room", label: "Clip Room", icon: MessagesSquare, hint: "Filter and review candidates" },
      { key: "gallery", label: "Gallery", icon: Image, hint: "Review and organize clips" },
      { key: "editor", label: "Editor", icon: Scissors, hint: "Edit clips and compilations" },
    ],
  },
  {
    label: "Your Clipper",
    items: [
      { key: "tutorial", label: "How it works", icon: BookOpenCheck, hint: "Replay the guided product tour" },
      { key: "onboarding", label: "Taste Setup", icon: ListChecks, hint: "Teach the clipper your style" },
      { key: "profile", label: "Profile Tuner", icon: Wand2, hint: "Review learned clip preferences" },
      { key: "language", label: "Language Studio", icon: Languages, hint: "Teach slang, names, and pronunciation" },
      { key: "account", label: "Account & Usage", icon: UserRound, hint: "Quota, devices, and sign out" },
      { key: "preferences", label: "Local Settings", icon: SettingsIcon, hint: "Models, workspace, and processing" },
    ],
  },
];

export const IS_CLIPPER = import.meta.env.VITE_APP_EDITION === "clipper";
export const NAV: NavSection[] = CLIPPER_NAV;

export const ICON_FOR_KIND: Record<string, LucideIcon> = {
  pipeline:         Cpu,
  batch:            Cpu,
  train_profile:    Brain,
  train_classifier: Brain,
  profile_suggest:  Wand2,
  caption_all:      Sparkles,
  voice_enroll:     Mic2,
  default:          Box,
};
