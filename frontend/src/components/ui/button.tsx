import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { type ButtonHTMLAttributes, forwardRef } from "react";
import { cn } from "@/lib/utils";
const variants = cva("inline-flex items-center justify-center rounded-sm text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-cyan-400 disabled:pointer-events-none disabled:opacity-50 active:translate-y-px", { variants: { variant: { default: "bg-cyan-400 text-zinc-950 hover:bg-cyan-300", outline: "border border-zinc-700 bg-zinc-900 text-zinc-100 hover:bg-zinc-800" }, size: { default: "h-8 px-3", icon: "h-8 w-8" } }, defaultVariants: { variant: "default", size: "default" } });
export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof variants> { asChild?: boolean }
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(({ className, variant, size, asChild = false, ...props }, ref) => { const Component = asChild ? Slot : "button"; return <Component className={cn(variants({ variant, size }), className)} ref={ref} {...props} />; });
Button.displayName = "Button";
