import { useNavigate, useParams } from "react-router-dom";
import { Mail, Send, X } from "lucide-react";
import { useProfile, useToggleFollowProfile } from "../hooks/queries";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { SubscribeButton } from "@/components/SubscribeButton";
import { UnclaimedNotice } from "@/components/UnclaimedNotice";
import { initialsOf } from "@/lib/mosaic";

// URL-driven profile overlay. Rendered by the background-location route in routes.tsx so
// the Directory stays mounted behind it; closing pops back to where you were.
export function ProfileSheet() {
  const { username } = useParams<{ username: string }>();
  const navigate = useNavigate();
  const { data: p, isLoading, isError } = useProfile(username ?? null);
  const toggle = useToggleFollowProfile(username ?? "");

  function close() {
    navigate(-1);
  }

  return (
    <Sheet open onOpenChange={(o) => !o && close()}>
      <SheetContent side="bottom" className="px-0 pb-0" hideClose>
        <div className="flex items-center px-4 pb-2 pt-3">
          <button
            type="button"
            onClick={close}
            className="ml-auto rounded-full p-1 text-muted-foreground opacity-70 transition-opacity hover:opacity-100 focus:outline-none"
          >
            <X className="size-5" />
            <span className="sr-only">Close</span>
          </button>
        </div>
        {isLoading ? (
          <p className="px-6 py-10 text-center text-muted-foreground">Loading…</p>
        ) : isError || !p ? (
          <p className="px-6 py-10 text-center text-muted-foreground">
            Couldn't load this profile.
          </p>
        ) : (
          <div className="px-6 pb-8">
            <div className="flex items-start gap-4">
              <Avatar className="size-16 border border-border">
                {p.profile_image_url && <AvatarImage src={p.profile_image_url} alt="" />}
                <AvatarFallback className="text-lg">
                  {initialsOf(p.display_name, p.username)}
                </AvatarFallback>
              </Avatar>
              <SheetHeader className="min-w-0 flex-1">
                <SheetTitle className="truncate text-2xl">
                  {p.display_name ?? "Unnamed"}
                </SheetTitle>
                <SheetDescription className="font-mono text-xs">
                  @{p.username}
                  {p.cities.length > 0 && ` · ${p.cities.join(" · ")}`}
                </SheetDescription>
              </SheetHeader>
            </div>

            {!p.verified ? (
              <div className="mt-4">
                <UnclaimedNotice name={p.display_name} canClaim={!p.has_email} />
              </div>
            ) : p.bio ? (
              <p className="mt-4 text-[15px] leading-relaxed text-foreground/85">{p.bio}</p>
            ) : null}

            {p.sources.length > 0 && (
              <Section label="Feeds">
                <ul className="flex flex-col gap-2">
                  {p.sources.map((s, i) => (
                    <li key={i} className="flex min-w-0 items-center gap-2">
                      <a
                        href={s.url}
                        target="_blank"
                        rel="noreferrer noopener"
                        className="truncate text-sm underline-offset-2 hover:underline"
                      >
                        {s.title ?? s.url}
                      </a>
                      <span className="shrink-0 rounded-full border border-border bg-secondary px-2 py-0.5 font-mono text-[10px] text-muted-foreground">
                        {s.label}
                      </span>
                      {s.status === "unverified" && (
                        <span className="shrink-0 rounded-full border border-[#e8d18a] bg-[#fdf0d5] px-2 py-0.5 font-mono text-[10px] text-[#8a6d1c]">
                          unverified
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              </Section>
            )}

            {p.links.length > 0 && (
              <Section label="Links">
                <div className="flex flex-wrap gap-1.5">
                  {p.links.map((l, i) => (
                    <a
                      key={i}
                      href={l.url}
                      target="_blank"
                      rel="noreferrer noopener"
                      className="rounded-full border border-border px-2.5 py-1 font-mono text-[11px] text-muted-foreground transition-colors hover:border-marigold hover:text-foreground"
                    >
                      {l.label}
                    </a>
                  ))}
                </div>
              </Section>
            )}

            <div className="mt-6 flex items-center gap-2">
              <SubscribeButton
                className="flex-1"
                hasFeeders={p.sources.length > 0}
                isSubscribed={p.is_subscribed}
                pending={toggle.isPending}
                onToggle={(subscribe) => toggle.mutate({ feederId: p.id, subscribe })}
                name={p.display_name}
              />
              {p.contact_email && (
                <Button asChild variant="outline" size="icon" aria-label="Email">
                  <a href={`mailto:${p.contact_email}`}>
                    <Mail />
                  </a>
                </Button>
              )}
              {p.contact_telegram && (
                <Button asChild variant="outline" size="icon" aria-label="Telegram">
                  <a
                    href={`https://t.me/${p.contact_telegram}`}
                    target="_blank"
                    rel="noreferrer noopener"
                  >
                    <Send />
                  </a>
                </Button>
              )}
            </div>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mt-5">
      <p className="mb-2 font-mono text-[10px] uppercase tracking-[0.12em] text-faint">
        {label}
      </p>
      {children}
    </div>
  );
}
