import type { HTMLAttributes } from 'react';

import { cn } from '../../lib/utils';

interface GlassCardProps extends HTMLAttributes<HTMLDivElement> {
    title?: string;
    neonAccent?: "green" | "red" | "blue" | "cyan" | "amber";
    rightElement?: React.ReactNode;
    children?: React.ReactNode;
    className?: string;
}

export function GlassCard({ title, children, className, neonAccent, rightElement, ...props }: GlassCardProps) {
    // Map accents to CSS variables/colors
    const borderColor = neonAccent === "green" ? "border-[#00ff9d]/30"
        : neonAccent === "red" ? "border-[#ff6b6b]/30"
            : neonAccent === "blue" ? "border-[#4361ee]/30"
                : neonAccent === "cyan" ? "border-[#00b4d8]/30"
                    : neonAccent === "amber" ? "border-[#ffd93d]/30"
                        : "border-white/10";

    const glowClass = neonAccent === "green" ? "shadow-[0_0_15px_rgba(0,255,157,0.1)]"
        : neonAccent === "red" ? "shadow-[0_0_15px_rgba(255,107,107,0.1)]"
            : neonAccent === "blue" ? "shadow-[0_0_15px_rgba(67,97,238,0.1)]"
                : "";

    return (
        <div
            className={cn(
                "relative overflow-hidden rounded-xl",
                "bg-white/5 backdrop-blur-md", // The Glass Effect
                "border transition-all duration-300",
                borderColor,
                glowClass,
                className
            )}
            {...props}
        >
            {/* Optional: Cyberpunk corner accent */}
            <div className={cn(
                "absolute top-0 left-0 w-2 h-2 border-t border-l rounded-tl-sm opacity-50",
                neonAccent === "green" ? "border-[#00ff9d]" :
                    neonAccent === "red" ? "border-[#ff6b6b]" :
                        "border-white/40"
            )} />

            {title && (
                <div className="px-5 py-3 border-b border-white/5 flex items-center justify-between">
                    <h3 className="text-sm font-header font-medium text-zinc-300 uppercase tracking-wider flex items-center gap-2">
                        {neonAccent && (
                            <div className={cn(
                                "w-1.5 h-1.5 rounded-full",
                                neonAccent === "green" ? "bg-[#00ff9d] shadow-[0_0_5px_#00ff9d]" :
                                    neonAccent === "red" ? "bg-[#ff6b6b] shadow-[0_0_5px_#ff6b6b]" :
                                        neonAccent === "blue" ? "bg-[#4361ee]" :
                                            "bg-zinc-500"
                            )} />
                        )}
                        {title}
                    </h3>
                    {rightElement}
                </div>
            )}
            <div className="p-5 flex-1 flex flex-col min-h-0">
                {children}
            </div>
        </div>
    );
}
