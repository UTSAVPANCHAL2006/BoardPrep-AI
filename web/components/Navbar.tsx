"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";

const NAV_LINKS = [
  { href: "/", label: "Home", scrollTo: null },
  { href: "/current-affairs", label: "Current Affairs", scrollTo: null },
  { href: "/#features", label: "Features", scrollTo: "features" },
  { href: "/#how-it-works", label: "How it works", scrollTo: "how-it-works" },
];

function scrollToSection(id: string) {
  const el = document.getElementById(id);
  if (el) {
    el.scrollIntoView({ behavior: "smooth", block: "start" });
    window.history.replaceState(null, "", `/#${id}`);
  }
}

export function Navbar() {
  const pathname = usePathname();
  const router = useRouter();
  const [open, setOpen] = useState(false);

  const isHome = pathname === "/";
  const isInterview = pathname.startsWith("/interview");
  const isFeedback = pathname.startsWith("/feedback");

  function handleNavClick(e: React.MouseEvent, scrollTo: string | null, href: string) {
    if (!scrollTo) return;
    if (!href.startsWith("/#")) return;
    e.preventDefault();
    setOpen(false);
    if (isHome) scrollToSection(scrollTo);
    else router.push(`/#${scrollTo}`);
  }

  return (
    <header className="sticky top-0 z-50 border-b border-white/[0.06] bg-navy-deep/80 backdrop-blur-2xl">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-3.5 md:px-6">
        <Link href="/" className="group flex items-center gap-3" onClick={() => setOpen(false)}>
          <div className="relative flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-saffron to-saffron-dark shadow-glow transition group-hover:shadow-glow-lg">
            <span className="text-[10px] font-black tracking-tight text-navy-deep">AI</span>
          </div>
          <div className="hidden sm:block">
            <p className="font-display text-base font-semibold leading-tight tracking-tight text-slate-100">
              BoardPrep
            </p>
            <p className="text-[9px] uppercase tracking-[0.18em] text-slate-500">UPSC Mock Interview</p>
          </div>
        </Link>

        <nav className="hidden items-center gap-1 md:flex">
          {NAV_LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              onClick={(e) => handleNavClick(e, link.scrollTo, link.href)}
              className={`rounded-lg px-3.5 py-2 text-sm font-medium transition ${
                (isHome && link.href === "/") || pathname === link.href
                  ? "bg-saffron/12 text-saffron"
                  : "text-slate-400 hover:bg-white/5 hover:text-slate-200"
              }`}
            >
              {link.label}
            </Link>
          ))}
        </nav>

        <div className="flex items-center gap-3">
          {isInterview && (
            <span className="hidden rounded-full bg-saffron/12 px-3 py-1 text-xs font-semibold text-saffron sm:inline">
              In session
            </span>
          )}
          {isFeedback && (
            <span className="hidden rounded-full bg-india-green/15 px-3 py-1 text-xs font-semibold text-india-green sm:inline">
              Report ready
            </span>
          )}

          {!isInterview && (
            <Link
              href="/"
              className="hidden rounded-xl bg-gradient-to-r from-saffron to-saffron-light px-4 py-2 text-sm font-semibold text-navy-deep shadow-glow transition hover:brightness-110 sm:inline-flex"
            >
              Start interview
            </Link>
          )}

          <button
            type="button"
            className="btn-icon md:hidden"
            onClick={() => setOpen((v) => !v)}
            aria-label="Toggle menu"
          >
            {open ? (
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            ) : (
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            )}
          </button>
        </div>
      </div>

      {open && (
        <div className="border-t border-white/[0.06] bg-navy-deep/95 px-5 py-4 backdrop-blur-xl md:hidden">
          <nav className="flex flex-col gap-1">
            {NAV_LINKS.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                onClick={(e) => handleNavClick(e, link.scrollTo, link.href)}
                className="rounded-xl px-4 py-3 text-sm font-medium text-slate-300 transition hover:bg-white/5 hover:text-white"
              >
                {link.label}
              </Link>
            ))}
          </nav>
          {!isInterview && (
            <Link
              href="/"
              onClick={() => setOpen(false)}
              className="mt-4 block rounded-xl bg-saffron py-2.5 text-center text-sm font-semibold text-navy-deep"
            >
              Start interview
            </Link>
          )}
        </div>
      )}
    </header>
  );
}
