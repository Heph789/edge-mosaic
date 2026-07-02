// Shown in place of the bio for a profile whose owner hasn't claimed it yet (unverified,
// pre-seeded). "Tell them to sign up!" opens the native share/contact sheet on mobile so the
// viewer can nudge them, falling back to an email draft on desktop. "Is this you?" is a
// placeholder for a future support/contact page where the real owner can claim the profile.
export function UnclaimedNotice({ name }: { name?: string | null }) {
  async function invite() {
    const who = name?.trim();
    const text = `${who ? `${who}, you` : "You"}'ve got a profile on Edge Mosaic — claim it and start sharing your feeds.`;
    const url = window.location.origin;
    if (typeof navigator !== "undefined" && navigator.share) {
      // Mobile: the OS share sheet lets the viewer pick any contact channel (SMS, mail, …).
      try {
        await navigator.share({ title: "Edge Mosaic", text, url });
      } catch {
        // Share sheet dismissed — nothing to do.
      }
      return;
    }
    // Desktop / no Web Share API: open an email draft as the equivalent contact option.
    window.location.href = `mailto:?subject=${encodeURIComponent(
      "Claim your Edge Mosaic profile"
    )}&body=${encodeURIComponent(`${text}\n\n${url}`)}`;
  }

  return (
    <div className="space-y-1.5">
      <p className="text-[15px] italic leading-relaxed text-muted-foreground">
        This user has not yet claimed their profile.{" "}
        <button
          type="button"
          onClick={invite}
          className="font-medium not-italic text-foreground underline underline-offset-2 hover:text-marigold"
        >
          Tell them to sign up!
        </button>
      </p>
      <button
        type="button"
        // TODO: route to a support/contact page so the real owner can claim this profile.
        className="text-xs italic text-faint underline underline-offset-2 transition-colors hover:text-foreground"
      >
        Is this you?
      </button>
    </div>
  );
}
