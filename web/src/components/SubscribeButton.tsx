import { useState } from "react";
import { Button, type ButtonProps } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

// Subscribe / Pre-Subscribe control shared by the directory list and both profile views.
// A feeder-less profile has nothing to send yet, so subscribing to it is a *pre*-subscribe:
// the copy changes and the first time you opt in we explain what that means via a modal.
export function SubscribeButton({
  hasFeeders,
  isSubscribed,
  pending,
  onToggle,
  name,
  className,
  size,
}: {
  hasFeeders: boolean;
  isSubscribed: boolean;
  pending: boolean;
  onToggle: (subscribe: boolean) => void;
  name?: string | null;
  className?: string;
  size?: ButtonProps["size"];
}) {
  const [explainOpen, setExplainOpen] = useState(false);

  const label = isSubscribed
    ? hasFeeders
      ? "✓ Subscribed"
      : "✓ Pre-Subscribed"
    : hasFeeders
      ? "Subscribe"
      : "Pre-Subscribe";

  function handleClick() {
    onToggle(!isSubscribed);
    // Pre-subscribing to a feeder-less profile: subscribe right away, then explain what
    // that means as an after-effect. Un-subscribing is silent.
    if (!hasFeeders && !isSubscribed) setExplainOpen(true);
  }

  const who = name?.trim() || "This person";

  return (
    <>
      <Button
        className={className}
        size={size}
        variant={isSubscribed ? "subscribed" : "default"}
        disabled={pending}
        onClick={(e) => {
          e.stopPropagation();
          handleClick();
        }}
      >
        {label}
      </Button>

      <Dialog open={explainOpen} onOpenChange={setExplainOpen}>
        <DialogContent
          className="max-w-sm rounded-xl"
          hideClose
          onClick={(e) => e.stopPropagation()}
        >
          <DialogHeader>
            <DialogTitle>Pre-Subscribed!</DialogTitle>
            <DialogDescription>
              {who} hasn’t added any feeds yet, so there’s nothing from them in your
              digest right now. The moment they add a feed, their new content starts
              showing up in your digests automatically.
            </DialogDescription>
          </DialogHeader>
          <div className="flex justify-end">
            <Button onClick={() => setExplainOpen(false)}>Sounds good!</Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
