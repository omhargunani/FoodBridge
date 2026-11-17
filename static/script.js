/* FoodBridge frontend - connected to the Flask + SQLite API.
   This file intentionally does not use localStorage for donations or requests. */

(() => {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  const API = {
    session: "/api/session",
    donations: "/api/donations",
    myDonations: "/api/my/donations",
    myRequests: "/api/my/requests",
    donorRequests: "/api/requests",
    createDonation: "/api/donations",
    cancelDonation: (id) => `/api/donations/${id}/cancel`,
    requestFood: (id) => `/api/donations/${id}/requests`,
    decideRequest: (id) => `/api/requests/${id}/decision`,
    completeRequest: (id) => `/api/requests/${id}/complete`
  };

  const viewTitles = {
    dashboard: "Dashboard",
    discover: "Find Food",
    donate: "Donate Food",
    donations: "My Donations",
    requests: "Food Requests"
  };

  const foodEmojis = {
    "Cooked Meals": "🍛",
    "Bakery": "🥐",
    "Fruits & Vegetables": "🥦",
    "Packaged Food": "🥫",
    "Dairy": "🥛",
    "Other": "🍱"
  };

  const categoryClasses = {
    "Cooked Meals": "meals",
    "Bakery": "bakery",
    "Fruits & Vegetables": "produce",
    "Packaged Food": "packaged",
    "Dairy": "dairy",
    "Other": "other"
  };

  let currentUser = null;
  let donations = [];
  let myDonations = [];
  let requests = [];
  let loading = false;

  function escapeHTML(value) {
    return String(value ?? "").replace(/[&<>"']/g, (character) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;"
    })[character]);
  }

  function showToast(message, isError = false) {
    const toast = $("#toast");
    if (!toast) {
      if (isError) console.error(message);
      else console.log(message);
      return;
    }
    toast.textContent = message;
    toast.classList.toggle("error", Boolean(isError));
    toast.classList.add("show");
    clearTimeout(showToast.timer);
    showToast.timer = setTimeout(() => toast.classList.remove("show"), 3500);
  }

  async function api(url, options = {}) {
    const response = await fetch(url, {
      credentials: "same-origin",
      cache: "no-store",
      ...options,
      headers: {
        Accept: "application/json",
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...(options.headers || {})
      }
    });

    if (response.status === 401) {
      window.location.replace("/login");
      throw new Error("Your session has expired. Please log in again.");
    }

    const contentType = response.headers.get("content-type") || "";
    let data = null;
    if (contentType.includes("application/json")) {
      data = await response.json();
    } else {
      const text = await response.text();
      data = text ? { error: text.slice(0, 250) } : {};
    }

    if (!response.ok) {
      throw new Error(data?.error || data?.message || `Request failed (${response.status}).`);
    }
    return data;
  }

  function formatDate(value) {
    if (!value) return "Not provided";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "Date unavailable";
    return date.toLocaleString("en-IN", {
      day: "numeric",
      month: "short",
      year: "numeric",
      hour: "numeric",
      minute: "2-digit"
    });
  }

  function isExpired(item) {
    return item?.deadline && new Date(item.deadline).getTime() <= Date.now()
      && !["completed", "cancelled"].includes(item.status);
  }

  function effectiveStatus(item) {
    return isExpired(item) ? "expired" : (item?.status || "unknown");
  }

  function statusLabel(status) {
    return ({
      available: "Available",
      requested: "Requested",
      accepted: "Accepted",
      completed: "Completed",
      cancelled: "Cancelled",
      expired: "Deadline passed",
      pending: "Pending",
      rejected: "Rejected"
    })[status] || status;
  }

  function emptyState(icon, title, description, buttonText, destination) {
    return `
      <div class="empty-state">
        <div class="empty-icon">${icon}</div>
        <h3>${escapeHTML(title)}</h3>
        <p>${escapeHTML(description)}</p>
        ${buttonText && destination ? `
          <button class="primary-button" type="button" data-go="${escapeHTML(destination)}">
            ${escapeHTML(buttonText)}
          </button>` : ""}
      </div>`;
  }

  function allKnownDonations() {
    const map = new Map();
    [...donations, ...myDonations].forEach((item) => map.set(String(item.id), item));
    return Array.from(map.values());
  }

  function getDonation(id) {
    return allKnownDonations().find((item) => String(item.id) === String(id));
  }

  function canCreateDonation() {
    return ["donor", "admin"].includes(currentUser?.role);
  }

  function canRequestFood() {
    return ["ngo", "recipient", "volunteer", "admin"].includes(currentUser?.role);
  }

  function donationCard(item) {
    const status = effectiveStatus(item);
    const category = escapeHTML(item.category || "Other");
    const emoji = foodEmojis[item.category] || "🍱";
    const cssClass = categoryClasses[item.category] || "other";
    // A donation can receive requests while its status is "requested".
    // Prevent the same receiver from requesting the same donation twice.
    const alreadyRequested = requests.some(
      (request) => String(request.donationId) === String(item.id)
    );

    const requestAllowed =
      canRequestFood() &&
      ["available", "requested"].includes(status) &&
      !alreadyRequested;

    const deadlineText = status === "expired" ? "Deadline passed" : formatDate(item.deadline);

    return `
      <article class="food-card">
        <div class="food-image ${cssClass}">
          <span>${emoji}</span>
          <span class="food-badge">${category}</span>
        </div>
        <div class="food-content">
          <h3>${escapeHTML(item.name)}</h3>
          <p class="food-description">${escapeHTML(item.quantity)}</p>
          <div class="food-meta">
            <span>♙ ${escapeHTML(item.donor || "Community donor")}</span>
            <span>⌖ ${escapeHTML(item.location)}</span>
            <span>♨ ${Number(item.servings || 0)} servings</span>
            <span>◷ ${escapeHTML(deadlineText)}</span>
          </div>
          <div class="food-footer">
            <strong>${escapeHTML(statusLabel(status))}</strong>
            ${canRequestFood() ? `
              <button class="primary-button" type="button"
                data-action="request" data-id="${escapeHTML(item.id)}"
                ${requestAllowed ? "" : "disabled"}>
                ${alreadyRequested ? "Already requested" :
                  requestAllowed ? "Request food" : "Unavailable"}
              </button>` : ""}
          </div>
        </div>
      </article>`;
  }

  function renderDashboard() {
    const available = donations.filter((item) => effectiveStatus(item) === "available");
    const completed = canCreateDonation()
      ? myDonations.filter((item) => effectiveStatus(item) === "completed")
      : requests.filter((item) => item.status === "completed");
    const totalCount = canCreateDonation() ? myDonations.length : donations.length;
    const mealCount = available.reduce((sum, item) => sum + Number(item.servings || 0), 0);

    if ($("#stat-donations")) $("#stat-donations").textContent = totalCount;
    if ($("#stat-meals")) $("#stat-meals").textContent = mealCount;
    if ($("#stat-requests")) $("#stat-requests").textContent = requests.length;
    if ($("#stat-completed")) $("#stat-completed").textContent = completed.length;

    const recent = [...available]
      .sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt))
      .slice(0, 3);

    const target = $("#recent-listings");
    if (target) {
      target.innerHTML = recent.length
        ? recent.map(donationCard).join("")
        : emptyState("🥗", "No food available right now",
            "Be the first to list a food donation.",
            canCreateDonation() ? "Donate food" : "", "donate");
    }
  }

  function renderDiscover() {
    const target = $("#all-listings");
    if (!target) return;

    const query = ($("#search-input")?.value || "").trim().toLowerCase();
    const category = $("#category-filter")?.value || "";

    const results = donations
      .filter((item) =>
        ["available", "requested"].includes(effectiveStatus(item))
      )
      .filter((item) => !category || item.category === category)
      .filter((item) => [
        item.name, item.location, item.donor, item.quantity, item.category
      ].join(" ").toLowerCase().includes(query))
      .sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));

    if ($("#listing-count")) {
      $("#listing-count").textContent =
        `${results.length} food listing${results.length === 1 ? "" : "s"} found`;
    }
    target.innerHTML = results.length
      ? results.map(donationCard).join("")
      : emptyState("🔎", "No matching food found",
          "Try another search or change the category.",
          canCreateDonation() ? "Donate food" : "", "donate");
  }

  function renderMyDonations() {
    const target = $("#my-donations");
    if (!target) return;

    if (!canCreateDonation()) {
      target.innerHTML = emptyState("🤝", "Donor workspace only",
        "Sign in with a donor account to manage donations.");
      return;
    }

    const sorted = [...myDonations].sort(
      (a, b) => new Date(b.createdAt) - new Date(a.createdAt)
    );

    target.innerHTML = sorted.length ? sorted.map((item) => {
      const status = effectiveStatus(item);
      const related = requests.filter((request) =>
        String(request.donationId) === String(item.id));
      const pending = related.filter((request) => request.status === "pending").length;

      return `
        <article class="management-card">
          <div class="management-emoji">${foodEmojis[item.category] || "🍱"}</div>
          <div class="management-info">
            <h3>${escapeHTML(item.name)}</h3>
            <p>${escapeHTML(item.quantity)} · ${Number(item.servings || 0)} servings</p>
            <p>⌖ ${escapeHTML(item.location)}</p>
            <p>Pickup deadline: ${escapeHTML(formatDate(item.deadline))}</p>
            <p><span class="status ${escapeHTML(status)}">${escapeHTML(statusLabel(status))}</span>
              ${pending ? ` · ${pending} pending request(s)` : ""}
            </p>
          </div>
          <div class="management-actions">
            ${["available", "requested"].includes(status) ? `
              <button class="outline-button" type="button"
                data-action="cancel-donation" data-id="${escapeHTML(item.id)}">
                Cancel listing
              </button>` : ""}
          </div>
        </article>`;
    }).join("") : emptyState("🥬", "No donations yet",
      "Your food donations will appear here.", "Create donation", "donate");
  }

  function renderRequests() {
    const target = $("#request-list");
    if (!target) return;

    if (!requests.length) {
      target.innerHTML = emptyState("🤝", "No food requests yet",
        canCreateDonation()
          ? "Requests for your donations will appear here."
          : "Your pickup requests will appear here.",
        canRequestFood() ? "Find food" : "", "discover");
      return;
    }

    target.innerHTML = [...requests]
      .sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt))
      .map((request) => {
        const donation = getDonation(request.donationId);
        const status = request.status || "pending";
        const canDecide = canCreateDonation() && status === "pending";
        const canComplete = status === "accepted" &&
          (canCreateDonation() || ["ngo", "recipient"].includes(currentUser?.role));

        return `
          <article class="management-card">
            <div class="management-emoji">
              ${foodEmojis[donation?.category] || "🍱"}
            </div>
            <div class="management-info">
              <h3>${escapeHTML(donation?.name || `Donation #${request.donationId}`)}</h3>
              <p>${canCreateDonation() ? "Requested by: " : "Donation request: "}
                ${escapeHTML(request.receiver || "Community receiver")}</p>
              <p>Request date: ${escapeHTML(formatDate(request.createdAt))}</p>
              <p><span class="status ${escapeHTML(status)}">${escapeHTML(statusLabel(status))}</span></p>
            </div>
            <div class="management-actions">
              ${canDecide ? `
                <button class="primary-button" type="button"
                  data-action="accept" data-id="${escapeHTML(request.id)}">Accept</button>
                <button class="outline-button" type="button"
                  data-action="reject" data-id="${escapeHTML(request.id)}">Reject</button>` : ""}
              ${canComplete ? `
                <button class="primary-button" type="button"
                  data-action="complete" data-id="${escapeHTML(request.id)}">Mark completed</button>` : ""}
            </div>
          </article>`;
      }).join("");
  }

  function renderAll() {
    renderDashboard();
    renderDiscover();
    renderMyDonations();
    renderRequests();
  }

  function navigate(viewName) {
    if (!viewTitles[viewName]) return;

    if (viewName === "donate" && !canCreateDonation()) {
      showToast("Only donor accounts can publish donations.", true);
      return;
    }
    if (viewName === "donations" && !canCreateDonation()) {
      showToast("This section is available to donors.", true);
      return;
    }

    $$(".view").forEach((view) => view.classList.toggle("active", view.id === viewName));
    $$("[data-view]").forEach((button) =>
      button.classList.toggle("active", button.dataset.view === viewName));
    if ($("#page-title")) $("#page-title").textContent = viewTitles[viewName];
    window.scrollTo({ top: 0, behavior: "smooth" });

    if (viewName === "discover") renderDiscover();
    if (viewName === "donations") renderMyDonations();
    if (viewName === "requests") renderRequests();
  }

  function configureRoleUI() {
    const donor = canCreateDonation();
    const receiver = canRequestFood();

    $$('[data-view="donate"], [data-go="donate"], .top-donate').forEach((element) => {
      element.hidden = !donor;
    });
    $$('[data-view="donations"], [data-go="donations"]').forEach((element) => {
      element.hidden = !donor;
    });

    const donorField = $('#donation-form [name="donor"]');
    if (donorField && currentUser?.name) donorField.value = currentUser.name;

    if (!donor && $("#donation-form")) {
      $("#donation-form").closest(".view")?.setAttribute("hidden", "");
    }
    if (donor && $("#donation-form")) {
      $("#donation-form").closest(".view")?.removeAttribute("hidden");
    }

    if (!receiver) {
      $$("#discover [data-action='request']").forEach((button) => button.remove());
    }
  }

  function setDeadlineMinimum() {
    const input = $('#donation-form [name="deadline"]');
    if (!input) return;
    const now = new Date();
    now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
    input.min = now.toISOString().slice(0, 16);
  }

  async function loadSession() {
    const data = await api(API.session);
    if (!data.authenticated || !data.user) {
      window.location.replace("/login");
      return false;
    }

    currentUser = data.user;
    const name = currentUser.name || currentUser.email || "Community Member";
    const role = currentUser.role || "member";

    if ($("#profile-name")) $("#profile-name").textContent = name;
    if ($("#profile-role")) {
      $("#profile-role").textContent = role.charAt(0).toUpperCase() + role.slice(1);
    }
    if ($("#profile-avatar")) {
      $("#profile-avatar").textContent = name.charAt(0).toUpperCase();
    }
    configureRoleUI();
    return true;
  }

  async function loadData() {
    const publicDonations = await api(API.donations);
    donations = Array.isArray(publicDonations) ? publicDonations : [];

    if (canCreateDonation()) {
      const own = await api(API.myDonations);
      myDonations = Array.isArray(own) ? own : [];
      const donorRequests = await api(API.donorRequests);
      requests = Array.isArray(donorRequests) ? donorRequests : [];
    } else {
      myDonations = [];
      const ownRequests = await api(API.myRequests);
      requests = Array.isArray(ownRequests) ? ownRequests : [];
    }
    renderAll();
  }

  async function createDonation(formData) {
    const deadlineInput = String(formData.get("deadline") || "");
    const deadline = new Date(deadlineInput);
    const servings = Number(formData.get("servings"));

    if (!Number.isFinite(deadline.getTime()) || deadline <= new Date()) {
      showToast("Choose a future food pickup deadline.", true);
      return;
    }
    if (!Number.isInteger(servings) || servings < 1 || servings > 100000) {
      showToast("Enter a valid number of servings.", true);
      return;
    }

    const payload = {
      name: String(formData.get("name") || "").trim(),
      category: String(formData.get("category") || ""),
      quantity: String(formData.get("quantity") || "").trim(),
      servings,
      location: String(formData.get("location") || "").trim(),
      contact: String(formData.get("contact") || "").trim(),
      deadline: deadline.toISOString(),
      notes: String(formData.get("notes") || "").trim()
    };

    try {
      const result = await api(API.createDonation, {
        method: "POST",
        body: JSON.stringify(payload)
      });
      $("#donation-form")?.reset();
      setDeadlineMinimum();
      await loadData();
      navigate("donations");
      showToast(result.message || "Donation published successfully.");
    } catch (error) {
      showToast(error.message, true);
    }
  }

  async function requestFood(id) {
    if (!canRequestFood()) {
      showToast("Please sign in with an NGO, recipient or volunteer account to request food.", true);
      return;
    }
    if (!confirm("Submit a pickup request for this food donation?")) return;

    try {
      const result = await api(API.requestFood(id), { method: "POST" });
      await loadData();
      navigate("requests");
      showToast(result.message || "Pickup request submitted successfully.");
    } catch (error) {
      showToast(error.message, true);
    }
  }

  async function cancelDonation(id) {
    if (!confirm("Cancel this food listing?")) return;
    try {
      const result = await api(API.cancelDonation(id), { method: "POST" });
      await loadData();
      showToast(result.message || "Donation cancelled.");
    } catch (error) {
      showToast(error.message, true);
    }
  }

  async function decideRequest(id, decision) {
    const label = decision === "accept" ? "accept" : "reject";
    if (!confirm(`Are you sure you want to ${label} this pickup request?`)) return;

    try {
      const result = await api(API.decideRequest(id), {
        method: "POST",
        body: JSON.stringify({ decision })
      });
      await loadData();
      showToast(result.message || `Request ${label}ed successfully.`);
    } catch (error) {
      showToast(error.message, true);
    }
  }

  async function completeRequest(id) {
    if (!confirm("Confirm that the food has been picked up and distributed?")) return;
    try {
      const result = await api(API.completeRequest(id), { method: "POST" });
      await loadData();
      showToast(result.message || "Pickup marked as completed.");
    } catch (error) {
      showToast(error.message, true);
    }
  }

  function bindEvents() {
    document.addEventListener("click", async (event) => {
      const nav = event.target.closest("[data-view]");
      if (nav) {
        event.preventDefault();
        navigate(nav.dataset.view);
        return;
      }

      const go = event.target.closest("[data-go]");
      if (go) {
        event.preventDefault();
        navigate(go.dataset.go);
        return;
      }

      const actionButton = event.target.closest("[data-action]");
      if (!actionButton) return;

      const { action, id } = actionButton.dataset;
      actionButton.disabled = true;

      try {
        if (action === "request") await requestFood(id);
        else if (action === "cancel-donation") await cancelDonation(id);
        else if (action === "accept") await decideRequest(id, "accept");
        else if (action === "reject") await decideRequest(id, "reject");
        else if (action === "complete") await completeRequest(id);
      } finally {
        if (document.body.contains(actionButton)) actionButton.disabled = false;
      }
    });

    const form = $("#donation-form");
    if (form) {
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        if (!canCreateDonation()) {
          showToast("Only donor accounts can publish donations.", true);
          return;
        }
        if (form.reportValidity()) createDonation(new FormData(form));
      });
      form.addEventListener("reset", () => setTimeout(setDeadlineMinimum, 0));
    }

    $("#search-input")?.addEventListener("input", renderDiscover);
    $("#category-filter")?.addEventListener("change", renderDiscover);

    const logoutForm = $("#logout-btn")?.closest("form");
    if (logoutForm) {
      logoutForm.addEventListener("submit", () => {
        const button = $("#logout-btn");
        if (button) {
          button.disabled = true;
          button.querySelector("span:last-child")?.replaceChildren("Signing out...");
        }
      });
    }
  }

  async function init() {
    if (loading) return;
    loading = true;
    bindEvents();
    setDeadlineMinimum();

    try {
      const authenticated = await loadSession();
      if (!authenticated) return;
      await loadData();
    } catch (error) {
      console.error("FoodBridge initialization error:", error);
      showToast(error.message || "Could not load FoodBridge. Refresh and try again.", true);
    } finally {
      loading = false;
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();
