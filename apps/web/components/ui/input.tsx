import * as React from "react";

import { cn } from "@/lib/utils";

export type InputProps = React.InputHTMLAttributes<HTMLInputElement>;

const Input = React.forwardRef<HTMLInputElement, InputProps>(({ className, type, ...props }, ref) => {
  return (
    <input
      type={type}
      className={cn(
        "h-10 w-full rounded-[8px] border border-white/10 bg-white/[0.06] px-3 py-2 text-sm text-white placeholder:text-white/38 outline-none transition focus:border-[#23d6a2]/70 focus:bg-white/[0.08]",
        className,
      )}
      ref={ref}
      {...props}
    />
  );
});
Input.displayName = "Input";

export { Input };
