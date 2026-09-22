import { useState } from "react";
import { motion, useReducedMotion } from "motion/react";

import { useDdragon } from "@/lib/ddragon";
import { EASE_OUT, MOTION } from "@/lib/motion";



/**
 * Full-bleed backdrop for the profile header: the main champion's splash art, darkened and
 * faded into the page background. Must sit inside a `relative isolate` parent at the top of
 * <main>; it bleeds up under the nav gap and out to both viewport edges.
 */
export function ProfileBanner({ champion }: { champion: string | null }) {
  const dd = useDdragon();
  const reduced = useReducedMotion();
  const src = champion ? dd.championSplash(champion) : "";
  const [loadedSrc, setLoadedSrc] = useState<string | null>(null);
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const showImage = src !== "" && failedSrc !== src;
  const loaded = loadedSrc === src;

  return (
    <div
      aria-hidden="true"
      className="pointer-events-none absolute -top-6 -bottom-12 -z-10 overflow-hidden [mask-image:linear-gradient(to_bottom,black_0%,black_45%,transparent_100%)] sm:-top-8"
      style={{ left: "calc(50% - 50vw)", right: "calc(50% - 50vw)" }}
    >
      {showImage ? (
        <motion.img
          key={src}
          src={src}
          alt=""
          decoding="async"
          draggable={false}
          onLoad={() => setLoadedSrc(src)}
          onError={() => setFailedSrc(src)}
          className="absolute inset-0 size-full object-cover object-[70%_18%] select-none sm:object-[center_20%]"
          initial={{ opacity: 0, scale: reduced ? 1 : 1.05 }}
          animate={loaded ? { opacity: 0.42, scale: 1 } : { opacity: 0, scale: reduced ? 1 : 1.05 }}
          transition={{ duration: reduced ? 0 : MOTION.countUp, ease: EASE_OUT }}
        />
      ) : null}
      {/* Brand glow so the header never looks empty (no main champion / image failed). */}
      <div className="absolute inset-0 bg-[radial-gradient(60%_90%_at_18%_10%,rgba(200,170,110,0.10),transparent_70%),radial-gradient(50%_80%_at_85%_30%,rgba(10,200,185,0.07),transparent_70%)]" />
      {/* Legibility: darken the text side; the mask above fades the whole banner into the page. */}
      <div className="absolute inset-0 bg-gradient-to-r from-bg/95 via-bg/70 to-bg/20" />
      <div className="absolute inset-0 bg-gradient-to-b from-bg/55 via-bg/15 to-bg/60" />
    </div>
  );
}
