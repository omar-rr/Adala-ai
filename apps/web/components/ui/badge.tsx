import * as React from "react";

import { cn } from "@/lib/utils";

export function Badge({ className, ...props }: React.HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-[8px] border border-white/10 bg-white/[0.06] px-2 py-1 text-[11px] font-medium text-white/72",
        className,
      )}
      {...props}
    />
  );
}

