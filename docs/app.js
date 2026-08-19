(() => {
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const coarsePointer = window.matchMedia("(pointer: coarse)").matches;

  const header = document.querySelector("[data-header]");
  const navToggle = document.querySelector("[data-nav-toggle]");
  const nav = document.querySelector("[data-nav]");

  const syncHeader = () => {
    header?.classList.toggle("is-scrolled", window.scrollY > 24);
  };

  syncHeader();
  window.addEventListener("scroll", syncHeader, { passive: true });

  navToggle?.addEventListener("click", () => {
    const open = navToggle.getAttribute("aria-expanded") === "true";
    navToggle.setAttribute("aria-expanded", String(!open));
    nav?.classList.toggle("is-open", !open);
  });

  nav?.querySelectorAll("a").forEach((link) => {
    link.addEventListener("click", () => {
      navToggle?.setAttribute("aria-expanded", "false");
      nav?.classList.remove("is-open");
    });
  });

  const revealItems = document.querySelectorAll(".reveal");
  if (reducedMotion || !("IntersectionObserver" in window)) {
    revealItems.forEach((item) => item.classList.add("is-visible"));
  } else {
    const revealObserver = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          entry.target.classList.add("is-visible");
          revealObserver.unobserve(entry.target);
        });
      },
      { threshold: 0.12, rootMargin: "0px 0px -6%" },
    );
    revealItems.forEach((item) => revealObserver.observe(item));
  }

  document.querySelectorAll(".bento").forEach((card) => {
    card.addEventListener("pointermove", (event) => {
      const rect = card.getBoundingClientRect();
      card.style.setProperty("--mx", `${event.clientX - rect.left}px`);
      card.style.setProperty("--my", `${event.clientY - rect.top}px`);
    });
  });

  if (!reducedMotion && !coarsePointer) {
    document.querySelectorAll("[data-tilt]").forEach((stage) => {
      const target = stage.querySelector(".visual-frame, .dashboard-frame");
      const strength = Number(stage.dataset.tiltStrength || 4);
      if (!target) return;

      stage.addEventListener("pointermove", (event) => {
        const rect = stage.getBoundingClientRect();
        const x = (event.clientX - rect.left) / rect.width - 0.5;
        const y = (event.clientY - rect.top) / rect.height - 0.5;
        target.style.transform = `rotateY(${x * strength}deg) rotateX(${-y * strength}deg)`;
      });

      stage.addEventListener("pointerleave", () => {
        target.style.transform = "";
      });
    });
  }

  const copyButton = document.querySelector("[data-copy]");
  const command = document.querySelector("[data-command] code");
  const toast = document.querySelector("[data-toast]");
  let toastTimer;

  copyButton?.addEventListener("click", async () => {
    if (!command) return;
    try {
      await navigator.clipboard.writeText(command.textContent.trim());
      copyButton.querySelector("span").textContent = "Copied";
      toast?.classList.add("is-visible");
      window.clearTimeout(toastTimer);
      toastTimer = window.setTimeout(() => {
        toast?.classList.remove("is-visible");
        copyButton.querySelector("span").textContent = "Copy";
      }, 1800);
    } catch {
      const selection = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(command);
      selection.removeAllRanges();
      selection.addRange(range);
    }
  });

  const canvas = document.querySelector("#signal-field");
  if (!canvas) return;

  const context = canvas.getContext("2d", { alpha: true });
  if (!context) return;

  let width = 0;
  let height = 0;
  let dpr = 1;
  let frameId = 0;
  let visible = true;
  let pointerX = 0;
  let pointerY = 0;

  const nodes = Array.from({ length: 74 }, (_, index) => {
    const radius = 160 + Math.random() * 430;
    const angle = Math.random() * Math.PI * 2;
    const elevation = (Math.random() - 0.5) * Math.PI;
    return {
      x: Math.cos(angle) * Math.cos(elevation) * radius,
      y: Math.sin(elevation) * radius * 0.72,
      z: Math.sin(angle) * Math.cos(elevation) * radius,
      size: index < 7 ? 2.1 : 0.6 + Math.random() * 1.15,
      accent: index < 7,
      phase: Math.random() * Math.PI * 2,
    };
  });

  const resize = () => {
    const rect = canvas.getBoundingClientRect();
    dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    width = Math.max(1, rect.width);
    height = Math.max(1, rect.height);
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    context.setTransform(dpr, 0, 0, dpr, 0, 0);
  };

  const rotate = (node, rotationY, rotationX) => {
    const cosY = Math.cos(rotationY);
    const sinY = Math.sin(rotationY);
    const x1 = node.x * cosY - node.z * sinY;
    const z1 = node.x * sinY + node.z * cosY;
    const cosX = Math.cos(rotationX);
    const sinX = Math.sin(rotationX);
    return {
      x: x1,
      y: node.y * cosX - z1 * sinX,
      z: node.y * sinX + z1 * cosX,
    };
  };

  const draw = (time = 0) => {
    if (!visible) return;
    context.clearRect(0, 0, width, height);

    const rotationY = (reducedMotion ? 0.42 : time * 0.000035) + pointerX * 0.16;
    const rotationX = -0.16 + pointerY * 0.08;
    const centerX = width * (width < 800 ? 0.5 : 0.68);
    const centerY = height * 0.46;
    const focal = Math.min(width, height) * 0.9;

    const projected = nodes.map((node) => {
      const rotated = rotate(node, rotationY + node.phase * 0.002, rotationX);
      const scale = focal / (focal + rotated.z + 520);
      return {
        x: centerX + rotated.x * scale,
        y: centerY + rotated.y * scale,
        z: rotated.z,
        scale,
        size: node.size,
        accent: node.accent,
      };
    });

    for (let i = 0; i < projected.length; i += 1) {
      const a = projected[i];
      for (let j = i + 1; j < projected.length; j += 1) {
        const b = projected[j];
        const dx = a.x - b.x;
        const dy = a.y - b.y;
        const distance = Math.hypot(dx, dy);
        if (distance > 92) continue;
        context.beginPath();
        context.moveTo(a.x, a.y);
        context.lineTo(b.x, b.y);
        const opacity = (1 - distance / 92) * 0.09 * Math.min(a.scale, b.scale);
        context.strokeStyle = `rgba(164, 177, 198, ${opacity})`;
        context.lineWidth = 0.7;
        context.stroke();
      }
    }

    projected
      .sort((a, b) => b.z - a.z)
      .forEach((point) => {
        const radius = Math.max(0.6, point.size * point.scale * 1.7);
        context.beginPath();
        context.arc(point.x, point.y, radius, 0, Math.PI * 2);
        context.fillStyle = point.accent
          ? `rgba(199, 255, 74, ${Math.min(0.9, point.scale)})`
          : `rgba(177, 189, 210, ${Math.min(0.5, point.scale * 0.45)})`;
        context.fill();

        if (point.accent) {
          context.beginPath();
          context.arc(point.x, point.y, radius * 4.8, 0, Math.PI * 2);
          const glow = context.createRadialGradient(point.x, point.y, 0, point.x, point.y, radius * 4.8);
          glow.addColorStop(0, "rgba(199, 255, 74, 0.22)");
          glow.addColorStop(1, "rgba(199, 255, 74, 0)");
          context.fillStyle = glow;
          context.fill();
        }
      });

    if (!reducedMotion) frameId = requestAnimationFrame(draw);
  };

  if ("IntersectionObserver" in window) {
    const canvasObserver = new IntersectionObserver((entries) => {
      visible = entries[0]?.isIntersecting ?? true;
      if (visible && !reducedMotion && !frameId) frameId = requestAnimationFrame(draw);
      if (!visible && frameId) {
        cancelAnimationFrame(frameId);
        frameId = 0;
      }
    });
    canvasObserver.observe(canvas);
  }
  window.addEventListener("resize", resize, { passive: true });
  window.addEventListener("pointermove", (event) => {
    pointerX = event.clientX / window.innerWidth - 0.5;
    pointerY = event.clientY / window.innerHeight - 0.5;
  }, { passive: true });

  resize();
  draw(0);
})();
