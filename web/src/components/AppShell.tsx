import { NavLink, Outlet } from "react-router-dom";
import { LayoutGrid, Newspaper, User } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

const TABS: { to: string; label: string; icon: LucideIcon }[] = [
  { to: "/directory", label: "Directory", icon: LayoutGrid },
  { to: "/digest", label: "Digest", icon: Newspaper },
  { to: "/profile", label: "Profile", icon: User },
];

// Mobile-first shell: content fills the screen, a bottom tab bar stays pinned. The
// global header/logout moved into the Profile tab so the mosaic gets full height.
export function AppShell() {
  return (
    <div className="flex h-full flex-col bg-background">
      <main className="relative min-h-0 flex-1">
        <Outlet />
      </main>
      <nav
        className="flex shrink-0 items-stretch border-t border-border bg-card"
        style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
      >
        {TABS.map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            className={({ isActive }) =>
              cn(
                "flex flex-1 flex-col items-center gap-1 py-2.5 text-[11px] font-medium transition-colors",
                isActive
                  ? "text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              )
            }
          >
            {({ isActive }) => (
              <>
                <t.icon
                  className={cn("size-[22px]", isActive && "text-marigold")}
                  strokeWidth={isActive ? 2.4 : 1.9}
                />
                {t.label}
              </>
            )}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
