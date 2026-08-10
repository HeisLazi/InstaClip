import { cn } from "@/lib/utils";
import { NAV, type PageKey } from "@/nav";

interface SidebarProps {
  current: PageKey;
  onSelect: (key: PageKey) => void;
  collapsed: boolean;
  onToggle: () => void;
}

export function Sidebar({ current, onSelect, collapsed, onToggle }: SidebarProps) {
  return (
    <aside
      className={cn(
        "glass-strong sidebar-shell shrink-0 border-r border-border/40 transition-[width] duration-200 ease-out",
        collapsed ? "w-[68px]" : "w-[232px]",
      )}
    >
      <div className="flex h-full flex-col">
        {/* Brand */}
        <button
          onClick={onToggle}
          className="flex h-16 items-center gap-3 px-4 hover:bg-accent/20 transition-colors"
          title={collapsed ? "Expand" : "Collapse"}
        >
          <div className="brand-mark grid h-8 w-8 place-items-center rounded-md text-primary-foreground text-sm font-bold">
            IC
          </div>
          {!collapsed && (
            <div className="leading-tight">
              <div className="text-sm font-semibold tracking-tight">InstaClip</div>
              <div className="text-[10px] uppercase tracking-widest text-muted-foreground">
                auto-clipper
              </div>
            </div>
          )}
        </button>

        <nav className="flex-1 overflow-y-auto px-2 py-3">
          {NAV.map((section) => (
            <div key={section.label} className="mb-4">
              {!collapsed && (
                <div className="px-2 mb-1 text-[10px] font-medium uppercase tracking-[0.12em] text-muted-foreground/80">
                  {section.label}
                </div>
              )}
              <div className="flex flex-col gap-0.5">
                {section.items.map((item) => {
                  const Icon = item.icon;
                  const active = current === item.key;
                  return (
                    <button
                      key={item.key}
                      onClick={() => onSelect(item.key)}
                      title={collapsed ? item.label : item.hint}
                      className={cn(
                        "group flex items-center gap-3 rounded-md px-2 py-2 text-sm transition-all duration-150",
                        active
                          ? "nav-item-active text-foreground"
                          : "text-muted-foreground hover:bg-accent/25 hover:text-foreground",
                      )}
                    >
                      <Icon className={cn("h-4 w-4 shrink-0",
                        active ? "text-primary" : "text-muted-foreground group-hover:text-foreground")} />
                      {!collapsed && (
                        <span className="truncate">{item.label}</span>
                      )}
                      {active && !collapsed && (
                        <span className="ml-auto h-1.5 w-1.5 rounded-full bg-primary shadow-[0_0_16px_hsl(var(--primary))]" />
                      )}
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>

        {/* Footer slot — version, theme toggle, etc. */}
        <div className="border-t border-border/40 px-3 py-3 text-[10px] text-muted-foreground">
          {!collapsed ? "v0.1.0 · local-first" : "v0"}
        </div>
      </div>
    </aside>
  );
}
