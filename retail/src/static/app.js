  (function(){
    "use strict";

    // ---- Bottom-nav registry ----
    // To add a feature: add an entry here, a matching <div class="tab-pane"
    // data-pane="KEY">, an i18n label, and (optionally) a per-tab loader below.
    const ICON = (paths) =>
      `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ` +
      `stroke-linecap="round" stroke-linejoin="round">${paths}</svg>`;
    const TAB_DEFS = [
      { key: "transfers",  i18n: "transfers_tab",
        icon: ICON('<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.7V20a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V9.7"/>') },
      { key: "card",       i18n: "card_tab",
        icon: ICON('<rect x="2.5" y="5" width="19" height="14" rx="3"/><path d="M2.5 9.5h19"/>') },
      { key: "creditcard", i18n: "cc_tab",
        icon: ICON('<path d="M12 3 21 9l-9 12L3 9z"/><path d="M3 9h18"/>') },
      { key: "savings",    i18n: "savings_tab",
        icon: ICON('<rect x="3" y="4.5" width="18" height="15" rx="2.5"/><circle cx="12" cy="12" r="3.3"/><path d="M12 8.7V6.5M12 17.5v-2.2"/>') },
      { key: "invest",     i18n: "invest_tab",
        icon: ICON('<path d="M3 17l6-6 4 4 7-7"/><path d="M17 8h4v4"/>') },
      { key: "brokerage",  i18n: "brokerage_tab",
        icon: ICON('<path d="M4 20V11M9 20V5M14 20V14M19 20V8"/>') },
      { key: "loans",      i18n: "loans_tab",
        icon: ICON('<circle cx="7.5" cy="7.5" r="2.4"/><circle cx="16.5" cy="16.5" r="2.4"/><path d="M18.5 5.5 5.5 18.5"/>') },
    ];

    // ---- i18n ----
    const i18n = {
      ru: {
        balance_label:    "остаток на счёте",
        profile:          "Профиль",
        transfers_tab:    "Переводы",
        card_tab:         "Карта",
        cc_tab:           "Кредитная",
        loans_tab:        "Кредиты",
        transfer_title:   "Перевести",
        to_label:         "Кому",
        to_placeholder:   "имя или ID получателя",
        amount_label:     "Сумма, ₽",
        transfer_btn:     "Перевести",
        recent_ops:       "Последние операции",
        no_ops:           "Операций пока нет",
        load_fail:        "Не удалось загрузить операции",
        fill_fields:      "введи получателя и сумму",
        insufficient_funds: "Недостаточно средств на счёте",
        amount_below_min: "Сумма меньше минимальной",
        overpay_debt:     "Сумма больше задолженности",
        sent:             "Отправлено",
        recipient:        "получатель",
        bank_client:      "клиент банка",
        external:         "внешний счёт",
        error:            "ошибка",
        server_down:      "сервер не ответил",
        transfer_in:      "Перевод входящий",
        transfer_out:     "Перевод исходящий",
        card_purchase:    "Оплата картой",
        atm_withdraw:     "Снятие в банкомате",
        salary:           "Зарплата",
        utility_payment:  "Коммунальные",
        toggle_label:     "EN",
        choose_product:   "Выберите продукт",
        loading_products: "Загрузка продуктов...",
        no_products:      "Продукты пока недоступны",
        rate_label:       "Ставка",
        loan_amount_title:"Сумма кредита",
        desired_amount:   "Желаемая сумма, ₽",
        apply_btn:        "Подать заявку",
        fill_amount:      "Укажите сумму кредита",
        approved:         "Одобрено!",
        declined:         "Отказано",
        approved_detail:  "Ваша заявка одобрена. Максимальная сумма",
        declined_detail:  "К сожалению, заявка отклонена",
        reason_label:     "Причина",
        products_error:   "Не удалось загрузить продукты",
        loading_card:     "Загрузка карты...",
        card_error:       "Не удалось загрузить данные карты",
        debit_card:       "ДЕБЕТОВАЯ",
        cashback_earned:  "Кешбэк",
        cashback_rate:    "Базовая ставка",
        cashback_history: "Кешбэк по операциям",
        no_cashback:      "Нет операций с кешбэком",
        cb_groceries:     "Продукты",
        cb_transport:     "Транспорт",
        cb_other:         "Прочее",
        your_segment:     "Ваш сегмент",
        savings_tab:      "Вклады",
        loading_savings:  "Загрузка вкладов...",
        savings_error:    "Не удалось загрузить данные о вкладах",
        your_savings:     "Ваши накопления",
        interest_earned:  "Начислено процентов",
        available_deposits: "Доступные вклады",
        no_deposit_products: "Вклады пока недоступны",
        per_year:         "годовых",
        open_deposit:     "Открыть вклад",
        deposit_amount:   "Сумма вклада, ₽",
        deposit_term:     "Срок, месяцев",
        deposit_open_btn: "Открыть",
        deposit_fill:     "Укажите сумму вклада",
        deposit_success:  "Вклад открыт!",
        estimated_income: "Ожидаемый доход",
        your_deposits:    "Ваши вклады",
        no_deposits:      "У вас пока нет вкладов",
        months:           "мес.",
        matures_at:       "Дата погашения",
        flexible:         "Снятие в любое время",
        deposit_maturity: "Погашение",
        invest_tab:       "Инвестиции",
        loading_invest:   "Загрузка инвестиций...",
        invest_error:     "Не удалось загрузить инвестиции",
        portfolio_value:  "Стоимость портфеля",
        your_portfolio:   "Ваш портфель",
        no_holdings:      "У вас пока нет инвестиций",
        available_instruments: "Доступные инструменты",
        no_instruments:   "Инструменты пока недоступны",
        exp_return:       "Ожид. доходность",
        risk_low:         "низкий риск",
        risk_medium:      "средний риск",
        risk_high:        "высокий риск",
        invest_now:       "Инвестировать",
        invest_amount:    "Сумма инвестиции, ₽",
        invest_btn:       "Купить",
        tap_to_invest:    "Нажмите, чтобы выбрать",
        invest_fill:      "Укажите сумму инвестиции",
        invest_success:   "Заявка принята!",
        projected_1y:     "Прогноз через год",
        brokerage_tab:    "Брокер",
        loading_brokerage: "Загрузка брокеража...",
        brokerage_error:  "Не удалось загрузить брокеридж",
        trading_cash:     "Свободные средства",
        positions_value:  "Стоимость позиций",
        your_positions:   "Ваши позиции",
        no_positions:     "У вас пока нет позиций",
        market:           "Рынок",
        no_securities:    "Бумаги недоступны",
        trade_buy:        "Купить",
        trade_sell:       "Продать",
        quantity:         "Количество",
        est_total:        "Примерно",
        commission_label: "Комиссия",
        order_done:       "Заявка исполнена",
        not_enough_units: "Недостаточно бумаг для продажи",
        qty_required:     "Укажите количество",
        units:            "шт.",
        tap_to_trade:     "Нажмите для сделки",
        order_rejected:   "Заявка отклонена",
        invested:         "Вложено",
        investor_profile_label: "Инвестиционный профиль",
        not_suitable:     "Не подходит вашему профилю",
        min_investment:   "Минимум",
        unsuitable_title: "Этот инструмент вам не подходит",
        suitable_alts:    "Подходящие альтернативы",
        loading_cc:       "Загрузка кредитной карты...",
        cc_error:         "Не удалось загрузить данные кредитной карты",
        credit_card:      "КРЕДИТНАЯ",
        cc_limit:         "Лимит",
        cc_owed:          "Задолженность",
        cc_available:     "Доступно",
        cc_min_payment:   "Мин. платёж",
        cc_interest:      "Процентная ставка",
        cc_grace:         "Льготный период",
        cc_days:          "дней",
        cc_pay_title:     "Погасить задолженность",
        cc_pay_amount:    "Сумма платежа, ₽",
        cc_pay_btn:       "Оплатить",
        cc_pay_success:   "Платёж принят",
        cc_not_eligible:  "Кредитная карта пока недоступна для данного клиента.",
        cc_fill_amount:   "Укажите сумму платежа",
        cc_used_of:       "использовано из",
        cc_secured:       "ЗАЩИЩЁННАЯ",
        cc_secured_note:  "Предложена защищённая кредитная карта",
      },
      en: {
        balance_label:    "account balance",
        profile:          "Profile",
        transfers_tab:    "Transfers",
        card_tab:         "Card",
        cc_tab:           "Credit",
        loans_tab:        "Loans",
        transfer_title:   "Send money",
        to_label:         "To",
        to_placeholder:   "name or recipient ID",
        amount_label:     "Amount, ₽",
        transfer_btn:     "Transfer",
        recent_ops:       "Recent transactions",
        no_ops:           "No transactions yet",
        load_fail:        "Could not load transactions",
        fill_fields:      "enter recipient and amount",
        insufficient_funds: "Insufficient funds on your account",
        amount_below_min: "Amount is below the minimum",
        overpay_debt:     "Amount exceeds the outstanding balance",
        sent:             "Sent",
        recipient:        "recipient",
        bank_client:      "bank client",
        external:         "external account",
        error:            "error",
        server_down:      "server did not respond",
        transfer_in:      "Incoming transfer",
        transfer_out:     "Outgoing transfer",
        card_purchase:    "Card purchase",
        atm_withdraw:     "ATM withdrawal",
        salary:           "Salary",
        utility_payment:  "Utilities",
        toggle_label:     "RU",
        choose_product:   "Choose a product",
        loading_products: "Loading products...",
        no_products:      "No products available yet",
        rate_label:       "Rate",
        loan_amount_title:"Loan amount",
        desired_amount:   "Desired amount, ₽",
        apply_btn:        "Apply for loan",
        fill_amount:      "Please enter a loan amount",
        approved:         "Approved!",
        declined:         "Declined",
        approved_detail:  "Your application is approved. Maximum amount",
        declined_detail:  "Unfortunately, your application was declined",
        reason_label:     "Reason",
        products_error:   "Could not load products",
        loading_card:     "Loading card...",
        card_error:       "Could not load card data",
        debit_card:       "DEBIT",
        cashback_earned:  "Cashback",
        cashback_rate:    "Base rate",
        cashback_history: "Cashback by transaction",
        no_cashback:      "No cashback transactions",
        cb_groceries:     "Groceries",
        cb_transport:     "Transport",
        cb_other:         "Other",
        your_segment:     "Your segment",
        savings_tab:      "Savings",
        loading_savings:  "Loading savings...",
        savings_error:    "Could not load savings data",
        your_savings:     "Your savings",
        interest_earned:  "Interest earned",
        available_deposits: "Available deposits",
        no_deposit_products: "No deposit products available yet",
        per_year:         "per year",
        open_deposit:     "Open a deposit",
        deposit_amount:   "Deposit amount, ₽",
        deposit_term:     "Term, months",
        deposit_open_btn: "Open",
        deposit_fill:     "Please enter a deposit amount",
        deposit_success:  "Deposit opened!",
        estimated_income: "Estimated income",
        your_deposits:    "Your deposits",
        no_deposits:      "You have no deposits yet",
        months:           "mo.",
        matures_at:       "Maturity date",
        flexible:         "Withdraw anytime",
        deposit_maturity: "Maturity",
        invest_tab:       "Invest",
        loading_invest:   "Loading investments...",
        invest_error:     "Could not load investments",
        portfolio_value:  "Portfolio value",
        your_portfolio:   "Your portfolio",
        no_holdings:      "You have no investments yet",
        available_instruments: "Available instruments",
        no_instruments:   "No instruments available yet",
        exp_return:       "Exp. return",
        risk_low:         "low risk",
        risk_medium:      "medium risk",
        risk_high:        "high risk",
        invest_now:       "Invest",
        invest_amount:    "Investment amount, ₽",
        invest_btn:       "Buy",
        tap_to_invest:    "Tap to select",
        invest_fill:      "Please enter an investment amount",
        invest_success:   "Order accepted!",
        projected_1y:     "1-year projection",
        brokerage_tab:    "Broker",
        loading_brokerage: "Loading brokerage...",
        brokerage_error:  "Could not load brokerage",
        trading_cash:     "Available cash",
        positions_value:  "Positions value",
        your_positions:   "Your positions",
        no_positions:     "You have no positions yet",
        market:           "Market",
        no_securities:    "No securities available",
        trade_buy:        "Buy",
        trade_sell:       "Sell",
        quantity:         "Quantity",
        est_total:        "Approx.",
        commission_label: "Commission",
        order_done:       "Order executed",
        not_enough_units: "Not enough units to sell",
        qty_required:     "Please enter a quantity",
        units:            "units",
        tap_to_trade:     "Tap to trade",
        order_rejected:   "Order rejected",
        invested:         "Invested",
        investor_profile_label: "Investor profile",
        not_suitable:     "Not suitable for your profile",
        min_investment:   "Minimum",
        unsuitable_title: "This instrument is not suitable for you",
        suitable_alts:    "Suitable alternatives",
        loading_cc:       "Loading credit card...",
        cc_error:         "Could not load credit card data",
        credit_card:      "CREDIT",
        cc_limit:         "Limit",
        cc_owed:          "Owed",
        cc_available:     "Available",
        cc_min_payment:   "Min. payment",
        cc_interest:      "Interest rate",
        cc_grace:         "Grace period",
        cc_days:          "days",
        cc_pay_title:     "Make a payment",
        cc_pay_amount:    "Payment amount, ₽",
        cc_pay_btn:       "Pay",
        cc_pay_success:   "Payment accepted",
        cc_not_eligible:  "Credit card is not available for this customer at the moment.",
        cc_fill_amount:   "Please enter a payment amount",
        cc_used_of:       "used of",
        cc_secured:       "SECURED",
        cc_secured_note:  "You have been offered a secured credit card",
      }
    };

    let lang = localStorage.getItem("raif_lang") || "ru";

    function t(key) { return (i18n[lang] || i18n.ru)[key] || key; }

    function applyLang() {
      document.documentElement.lang = lang;
      document.querySelectorAll("[data-i18n]").forEach(el => {
        el.textContent = t(el.dataset.i18n);
      });
      document.querySelectorAll("[data-i18n-placeholder]").forEach(el => {
        el.placeholder = t(el.dataset.i18nPlaceholder);
      });
      document.getElementById("lang-toggle").textContent = t("toggle_label");
      const opt = sel.selectedOptions[0];
      if (opt) {
        loadTx(opt.value);
        loadCardInfo(opt.value);
        loadCreditCard(opt.value);
        loadSavings(opt.value);
        loadInvest(opt.value);
        loadBrokerage(opt.value);
      }
      if (productsData.length) renderProducts();
    }

    document.getElementById("lang-toggle").addEventListener("click", () => {
      lang = lang === "ru" ? "en" : "ru";
      localStorage.setItem("raif_lang", lang);
      applyLang();
    });

    const fmt = new Intl.NumberFormat("ru-RU");
    const sel = document.getElementById("client-select");
    const balanceV = document.getElementById("balance-v");
    const topbarWho = document.getElementById("topbar-who");
    const txList = document.getElementById("tx-list");
    const transferResult = document.getElementById("transfer-result");
    const productList = document.getElementById("product-list");
    const loanApplySection = document.getElementById("loan-apply-section");
    const loanResult = document.getElementById("loan-result");
    const cardContainer = document.getElementById("card-container");
    const ccContainer = document.getElementById("cc-container");
    const savingsContainer = document.getElementById("savings-container");
    const investContainer = document.getElementById("invest-container");
    const brokerageContainer = document.getElementById("brokerage-container");

    // ---- tabs (built from TAB_DEFS) ----
    document.querySelector(".tabs").innerHTML = TAB_DEFS.map((tdef, i) =>
      `<button class="tab${i === 0 ? " active" : ""}" data-tab="${tdef.key}">
         <span class="tab-ic">${tdef.icon}</span>
         <span class="tab-lb" data-i18n="${tdef.i18n}">${tdef.key}</span>
       </button>`).join("");

    document.querySelectorAll(".tab").forEach(btn => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".tab").forEach(b => b.classList.remove("active"));
        document.querySelectorAll(".tab-pane").forEach(p => p.classList.remove("show"));
        btn.classList.add("active");
        document.querySelector(`[data-pane="${btn.dataset.tab}"]`).classList.add("show");
        const opt = sel.selectedOptions[0];
        if (opt && btn.dataset.tab === "card") loadCardInfo(opt.value);
        if (opt && btn.dataset.tab === "creditcard") loadCreditCard(opt.value);
        if (opt && btn.dataset.tab === "savings") loadSavings(opt.value);
        if (opt && btn.dataset.tab === "invest") loadInvest(opt.value);
        if (opt && btn.dataset.tab === "brokerage") loadBrokerage(opt.value);
      });
    });

    // ---- load clients ----
    async function loadClients() {
      try {
        const r = await fetch("/clients?limit=200");
        const d = await r.json();
        const items = (d.items || []).slice(0, 80);
        sel.innerHTML = items.map(c =>
          `<option value="${c.id}" data-balance="${c.balance_rub}" data-name="${c.name}" data-segment="${c.segment}">
            ${c.name}
          </option>`
        ).join("");
        if (items.length) onPickClient();
      } catch(e) { console.error(e); }
    }

    function onPickClient() {
      const opt = sel.selectedOptions[0];
      if (!opt) return;
      balanceV.textContent = fmt.format(+opt.dataset.balance || 0);
      topbarWho.textContent = opt.dataset.name;
      loadTx(opt.value);
      loadCardInfo(opt.value);
      loadCreditCard(opt.value);
      loadSavings(opt.value);
      loadInvest(opt.value);
      loadBrokerage(opt.value);
      loanResult.innerHTML = "";
    }
    sel.addEventListener("change", onPickClient);

    // ---- transactions ----
    async function loadTx(clientId) {
      try {
        const r = await fetch(`/transactions/${clientId}?limit=10`);
        const d = await r.json();
        const items = d.items || [];
        if (!items.length) {
          txList.innerHTML = `<div class="empty">${t("no_ops")}</div>`;
          return;
        }
        txList.innerHTML = items.map(tx => {
          const sign = tx.amount_rub >= 0 ? "plus" : "minus";
          const amt = (tx.amount_rub >= 0 ? "+" : "−") + fmt.format(Math.abs(tx.amount_rub));
          const niceTs = tx.ts.replace("T", " ").slice(0, 16);
          return `<div class="tx-row">
            <div>
              <div class="desc">${typeLabel(tx.type)}</div>
              <div class="ts">${niceTs}</div>
            </div>
            <div class="amt ${sign}">${amt} ₽</div>
          </div>`;
        }).join("");
      } catch(e) {
        txList.innerHTML = `<div class="empty">${t("load_fail")}</div>`;
      }
    }

    function typeLabel(tp) { return t(tp) || tp; }

    function setBalance(newAmount) {
      balanceV.textContent = fmt.format(newAmount);
      const opt = sel.selectedOptions[0];
      if (opt) opt.dataset.balance = newAmount;
    }

    // Money a customer actually has available right now (client-side guard).
    // The authoritative check still belongs to the backend, which must debit.
    function availableBalance() {
      const opt = sel.selectedOptions[0];
      return opt ? (+opt.dataset.balance || 0) : 0;
    }

    // ---- transfer form ----
    const transferForm = document.getElementById("transfer-form");
    transferForm.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      transferResult.innerHTML = "";
      const opt = sel.selectedOptions[0];
      if (!opt) return;
      const data = new FormData(ev.target);
      const to = (data.get("to") || "").trim();
      const amount = +data.get("amount");
      if (!to || amount <= 0) {
        transferResult.innerHTML = `<div class="alert error">${t("fill_fields")}</div>`;
        return;
      }
      if (amount > availableBalance()) {
        transferResult.innerHTML = `<div class="alert error">${t("insufficient_funds")}</div>`;
        return;
      }
      const payload = { from_client_id: opt.value, to, amount_rub: amount };
      try {
        const r = await fetch("/api/transfer", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify(payload),
        });
        const d = await r.json();
        if (r.ok) {
          const kindLabel = d.kind === "internal"
            ? `${d.to} (${t("bank_client")})` : `${d.to} (${t("external")})`;
          transferResult.innerHTML =
            `<div class="alert ok">${t("sent")} ${fmt.format(d.amount_rub)} ₽<br/>
             ${t("recipient")}: ${kindLabel}</div>`;
          setBalance(d.new_balance_rub);
          transferForm.reset();
          loadTx(opt.value);
        } else {
          transferResult.innerHTML = `<div class="alert error">${d.detail || t("error")}</div>`;
        }
      } catch(e) {
        transferResult.innerHTML = `<div class="alert error">${t("server_down")}</div>`;
      }
    });

    // ---- Debit card with cashback ----
    async function loadCardInfo(clientId) {
      try {
        const r = await fetch(`/api/card-info/${clientId}`);
        if (!r.ok) throw new Error("failed");
        renderCard(await r.json());
      } catch(e) {
        cardContainer.innerHTML = `<div class="empty">${t("card_error")}</div>`;
      }
    }

    function renderCard(data) {
      const cbTxs = data.cashback_transactions || [];
      let cbTxsHtml = "";
      if (cbTxs.length) {
        cbTxsHtml = cbTxs.map(tx => {
          const niceTs = tx.ts.replace("T", " ").slice(0, 16);
          return `<div class="cashback-tx-row">
            <div>
              <div class="cb-tx-desc">${typeLabel(tx.type)}</div>
              <div class="cb-tx-ts">${niceTs}</div>
            </div>
            <div class="cb-tx-amount">${fmt.format(Math.abs(tx.amount_rub))} ₽</div>
            <div class="cb-tx-cashback">+${fmt.format(tx.cashback_rub)} ₽</div>
          </div>`;
        }).join("");
      } else {
        cbTxsHtml = `<div class="empty">${t("no_cashback")}</div>`;
      }
      // Build personalised rates display
      const cibRates = data.cashback_rates_pct || {};
      const hasCibRates = Object.keys(cibRates).length > 0;
      let ratesHtml = "";
      if (hasCibRates) {
        ratesHtml = `
          <div class="cashback-summary">
            <div class="cashback-box">
              <div class="cb-value">${cibRates.groceries || 0}%</div>
              <div class="cb-label">${t("cb_groceries")}</div>
            </div>
            <div class="cashback-box">
              <div class="cb-value">${cibRates.transport || 0}%</div>
              <div class="cb-label">${t("cb_transport")}</div>
            </div>
            <div class="cashback-box">
              <div class="cb-value">${cibRates.other || 0}%</div>
              <div class="cb-label">${t("cb_other")}</div>
            </div>
          </div>`;
      } else {
        ratesHtml = `
          <div class="cashback-summary">
            <div class="cashback-box">
              <div class="cb-value">1%</div>
              <div class="cb-label">${t("cashback_rate")}</div>
            </div>
          </div>`;
      }

      const segmentLabel = data.segment
        ? `<div style="font-size:12px;color:var(--muted);margin-bottom:12px">${t("your_segment")}: ${data.segment}</div>`
        : "";

      cardContainer.innerHTML = `
        <div class="debit-card">
          <div class="card-bank">Raiffeisen</div>
          <div class="card-number">${data.card_number_masked}</div>
          <div class="card-bottom">
            <div class="card-holder">${data.customer_name}</div>
            <div class="card-type">${t("debit_card")}</div>
          </div>
        </div>
        ${segmentLabel}
        <div class="cashback-summary">
          <div class="cashback-box">
            <div class="cb-value">${fmt.format(data.total_cashback_rub)} ₽</div>
            <div class="cb-label">${t("cashback_earned")}</div>
          </div>
        </div>
        ${ratesHtml}
        <div class="section-title">${t("cashback_history")}</div>
        <div class="tx-list">${cbTxsHtml}</div>`;
    }

    // ---- Credit card ----
    let ccData = null;

    async function loadCreditCard(clientId) {
      try {
        const r = await fetch(`/api/credit-card/${clientId}`);
        if (!r.ok) throw new Error("failed");
        ccData = await r.json();
        renderCreditCard(ccData);
      } catch(e) {
        ccContainer.innerHTML = `<div class="empty">${t("cc_error")}</div>`;
      }
    }

    function renderCreditCard(d) {
      if (!d.eligible) {
        ccContainer.innerHTML = `<div class="cc-not-eligible">
          ${t("cc_not_eligible")}<br/>
          <span style="font-size:12px;color:var(--muted)">${d.explanation || ""}</span>
        </div>`;
        return;
      }

      const isSecured = d.is_secured || d.product_id === "card-credit-secured";
      const cardLabel = isSecured ? t("cc_secured") : t("credit_card");
      const cardColor = isSecured
        ? "background: linear-gradient(135deg, #3a2a1a 0%, #6a4a2a 50%, #3a2a1a 100%)"
        : "";

      const securedNote = isSecured && d.explanation
        ? `<div class="alert info" style="margin-bottom:14px">${t("cc_secured_note")}: ${d.explanation}</div>`
        : "";

      const usedPct = d.credit_limit_rub > 0
        ? Math.round((d.balance_owed_rub / d.credit_limit_rub) * 100) : 0;
      const barClass = usedPct < 30 ? "low" : usedPct > 70 ? "high" : "";

      const paymentSection = d.balance_owed_rub > 0 ? `
        <div class="section-title" style="margin-top:18px">${t("cc_pay_title")}</div>
        <form id="cc-pay-form" autocomplete="off">
          <div class="form-row">
            <label>${t("cc_pay_amount")}</label>
            <input name="cc_amount" type="number" min="1" placeholder="${fmt.format(d.min_payment_rub)}" />
          </div>
          <button class="btn primary" type="submit">${t("cc_pay_btn")}</button>
        </form>
        <div id="cc-pay-result"></div>
      ` : "";

      ccContainer.innerHTML = `
        ${securedNote}
        <div class="credit-card-visual" ${cardColor ? `style="${cardColor}"` : ""}>
          <div class="card-bank">Raiffeisen</div>
          <div class="card-number">${d.card_number_masked}</div>
          <div class="card-bottom">
            <div class="card-holder">${d.customer_name}</div>
            <div class="card-type">${cardLabel}</div>
          </div>
        </div>

        <div class="cc-summary">
          <div class="cc-box">
            <div class="cc-value ${d.balance_owed_rub > 0 ? 'warn' : ''}">${fmt.format(d.balance_owed_rub)} ₽</div>
            <div class="cc-label">${t("cc_owed")}</div>
          </div>
          <div class="cc-box">
            <div class="cc-value">${fmt.format(d.available_rub)} ₽</div>
            <div class="cc-label">${t("cc_available")}</div>
          </div>
        </div>

        <div style="font-size:12px;color:var(--muted);margin-bottom:6px">
          ${fmt.format(d.balance_owed_rub)} ₽ ${t("cc_used_of")} ${fmt.format(d.credit_limit_rub)} ₽
        </div>
        <div class="cc-limit-bar">
          <div class="cc-used ${barClass}" style="width:${usedPct}%"></div>
        </div>

        <div class="cc-details">
          <div class="cc-detail-row">
            <span class="cc-dl">${t("cc_limit")}</span>
            <span class="cc-dv">${fmt.format(d.credit_limit_rub)} ₽</span>
          </div>
          ${d.min_payment_rub > 0 ? `<div class="cc-detail-row">
            <span class="cc-dl">${t("cc_min_payment")}</span>
            <span class="cc-dv">${fmt.format(d.min_payment_rub)} ₽</span>
          </div>` : ""}
          <div class="cc-detail-row">
            <span class="cc-dl">${t("cc_interest")}</span>
            <span class="cc-dv">${d.interest_rate_pct}%</span>
          </div>
          <div class="cc-detail-row">
            <span class="cc-dl">${t("cc_grace")}</span>
            <span class="cc-dv">${d.grace_period_days} ${t("cc_days")}</span>
          </div>
        </div>

        ${paymentSection}`;

      // Attach payment form handler
      const payForm = document.getElementById("cc-pay-form");
      if (payForm) {
        payForm.addEventListener("submit", async (ev) => {
          ev.preventDefault();
          const payResult = document.getElementById("cc-pay-result");
          payResult.innerHTML = "";
          const amount = +new FormData(ev.target).get("cc_amount");
          if (!amount || amount <= 0) {
            payResult.innerHTML = `<div class="alert error">${t("cc_fill_amount")}</div>`;
            return;
          }
          if (amount > (d.balance_owed_rub || 0)) {
            payResult.innerHTML = `<div class="alert error">${t("overpay_debt")}</div>`;
            return;
          }
          if (amount > availableBalance()) {
            payResult.innerHTML = `<div class="alert error">${t("insufficient_funds")}</div>`;
            return;
          }
          try {
            const r = await fetch("/api/credit-card-payment", {
              method: "POST", headers: {"Content-Type": "application/json"},
              body: JSON.stringify({ client_id: d.client_id, amount_rub: amount }),
            });
            const res = await r.json();
            if (r.ok) {
              payResult.innerHTML = `<div class="alert ok">${t("cc_pay_success")}: ${fmt.format(amount)} ₽</div>`;
              payForm.reset();
              // Refresh the credit card view
              setTimeout(() => loadCreditCard(d.client_id), 500);
            } else {
              payResult.innerHTML = `<div class="alert error">${res.detail || t("error")}</div>`;
            }
          } catch(e) {
            payResult.innerHTML = `<div class="alert error">${t("server_down")}</div>`;
          }
        });
      }
    }

    // ---- Savings / Deposits ----
    let savingsData = null;
    let selectedDepositId = null;

    async function loadSavings(clientId) {
      try {
        const r = await fetch(`/api/deposits/${clientId}`);
        if (!r.ok) throw new Error("failed");
        savingsData = await r.json();
        renderSavings(savingsData);
      } catch(e) {
        savingsContainer.innerHTML = `<div class="empty">${t("savings_error")}</div>`;
      }
    }

    function renderSavings(d) {
      const products = d.deposit_products || [];
      const existing = d.existing_deposits || [];

      // Hero: total savings summary
      const heroHtml = `
        <div class="savings-hero">
          <div class="sh-label">${t("your_savings")}</div>
          <div class="sh-value">${fmt.format(d.total_deposited_rub)} ₽</div>
          ${d.total_interest_rub > 0
            ? `<div class="sh-interest">+${fmt.format(d.total_interest_rub)} ₽ ${t("interest_earned")}</div>`
            : ""}
        </div>`;

      // Existing deposits
      let existingHtml = "";
      if (existing.length) {
        existingHtml = `<div class="section-title">${t("your_deposits")}</div>` +
          existing.map(dep => `
            <div class="existing-deposit">
              <div class="ed-top">
                <span class="ed-name">${dep.product_name || dep.product_id}</span>
                <span class="ed-amount">${fmt.format(dep.amount_rub)} ₽</span>
              </div>
              <div class="ed-detail">
                ${dep.rate_pct || ""}% · ${dep.term_months || ""} ${t("months")}
                ${dep.interest_earned_rub ? ` · +${fmt.format(dep.interest_earned_rub)} ₽` : ""}
              </div>
            </div>
          `).join("");
      }

      // Available deposit products
      let productsHtml = "";
      if (products.length) {
        productsHtml = `<div class="section-title" style="margin-top:18px">${t("available_deposits")}</div>` +
          products.map(p => {
            const sel = p.id === selectedDepositId ? "selected" : "";
            return `<div class="deposit-offer ${sel}" data-deposit-id="${p.id}">
              <div class="do-top">
                <span class="do-name">${p.name}</span>
                <span class="do-rate">${p.rate_pct || ""}% <small>${t("per_year")}</small></span>
              </div>
              <div class="do-detail">${p.description || ""}</div>
            </div>`;
          }).join("");
      } else {
        productsHtml = `<div class="empty" style="padding:20px 0">${t("no_deposit_products")}</div>`;
      }

      // Open deposit form (no term selector — term comes from the product)
      const formHtml = products.length ? `
        <div id="deposit-open-section" style="display:${selectedDepositId ? 'block' : 'none'}; margin-top:18px">
          <div class="section-title">${t("open_deposit")}</div>
          <form id="deposit-open-form" autocomplete="off">
            <div class="form-row">
              <label>${t("deposit_amount")}</label>
              <input name="dep_amount" type="number" min="1000" step="1000" placeholder="100 000" />
            </div>
            <button class="btn primary" type="submit">${t("deposit_open_btn")}</button>
          </form>
          <div id="deposit-result"></div>
        </div>
      ` : "";

      savingsContainer.innerHTML = heroHtml + existingHtml + productsHtml + formHtml;

      // Attach click handlers to deposit offers
      savingsContainer.querySelectorAll(".deposit-offer").forEach(card => {
        card.addEventListener("click", () => {
          selectedDepositId = card.dataset.depositId;
          savingsContainer.querySelectorAll(".deposit-offer").forEach(c => c.classList.remove("selected"));
          card.classList.add("selected");
          const section = document.getElementById("deposit-open-section");
          if (section) section.style.display = "block";
        });
      });

      // Attach form handler
      const depForm = document.getElementById("deposit-open-form");
      if (depForm) {
        depForm.addEventListener("submit", async (ev) => {
          ev.preventDefault();
          const depResult = document.getElementById("deposit-result");
          depResult.innerHTML = "";
          const fd = new FormData(ev.target);
          const amount = +fd.get("dep_amount");
          if (!amount || amount <= 0) {
            depResult.innerHTML = `<div class="alert error">${t("deposit_fill")}</div>`;
            return;
          }
          if (amount > availableBalance()) {
            depResult.innerHTML = `<div class="alert error">${t("insufficient_funds")}</div>`;
            return;
          }
          if (!selectedDepositId) return;
          try {
            const r = await fetch("/api/deposit-open", {
              method: "POST", headers: {"Content-Type": "application/json"},
              body: JSON.stringify({
                client_id: d.client_id,
                product_id: selectedDepositId,
                amount_rub: amount,
              }),
            });
            const res = await r.json();
            if (r.ok) {
              const estIncome = res.estimated_interest_rub
                ? `${t("estimated_income")}: +${fmt.format(res.estimated_interest_rub)} ₽`
                : "";
              const maturity = res.matures_at
                ? `<br/>${t("deposit_maturity")}: ${res.matures_at}`
                : (res.early_withdrawal ? `<br/>${t("flexible")}` : "");
              const termInfo = res.term_months
                ? ` · ${res.term_months} ${t("months")}`
                : "";
              const prodName = res.product_name ? `${res.product_name} — ` : "";
              depResult.innerHTML = `<div class="alert ok">
                ${t("deposit_success")} ${prodName}${fmt.format(res.amount_rub || amount)} ₽ · ${res.rate_pct}%${termInfo}<br/>
                ${estIncome}${maturity}
              </div>`;
              depForm.reset();
              setTimeout(() => loadSavings(d.client_id), 500);
            } else {
              depResult.innerHTML = `<div class="alert error">${res.detail || t("error")}</div>`;
            }
          } catch(e) {
            depResult.innerHTML = `<div class="alert error">${t("server_down")}</div>`;
          }
        });
      }
    }

    // ---- Brokerage ----
    let brokerageData = null;
    let selectedSecId = null;
    let selectedSide = "buy";

    async function loadBrokerage(clientId) {
      try {
        const r = await fetch(`/api/brokerage/${clientId}`);
        if (!r.ok) throw new Error("failed");
        brokerageData = await r.json();
        renderBrokerage(brokerageData);
      } catch (e) {
        brokerageContainer.innerHTML = `<div class="empty">${t("brokerage_error")}</div>`;
      }
    }

    function ownedQty(secId) {
      const p = (brokerageData?.positions || []).find(x => x.security_id === secId);
      return p ? p.quantity : 0;
    }

    function updateTradeEstimate() {
      const est = document.getElementById("trade-est");
      if (!est) return;
      const sec = (brokerageData?.securities || []).find(s => s.id === selectedSecId);
      const qty = +(document.querySelector('#brokerage-container input[name="qty"]')?.value || 0);
      if (!sec || !qty) { est.textContent = ""; return; }
      est.textContent = `${t("est_total")}: ${fmt.format(Math.round(sec.price_rub * qty))} ₽`;
    }

    function renderBrokerage(d) {
      const secs = d.securities || [];
      const positions = d.positions || [];

      const pl = d.total_pl_rub || 0;
      const plDir = pl > 0 ? "up" : pl < 0 ? "down" : "flat";
      const plSign = pl > 0 ? "+" : "";
      const heroHtml = `
        <div class="brokerage-hero">
          <div class="bh-label">${t("trading_cash")}</div>
          <div class="bh-value">${fmt.format(d.cash_rub)} ₽</div>
          <div class="bh-sub">
            ${t("positions_value")}: ${fmt.format(d.total_positions_value_rub)} ₽
            <span class="bh-pl ${plDir}">${plSign}${fmt.format(pl)} ₽</span>
          </div>
        </div>`;

      let posHtml = "";
      if (positions.length) {
        posHtml = `<div class="section-title">${t("your_positions")}</div>` +
          positions.map(p => {
            const dir = (p.pl_rub || 0) >= 0 ? "up" : "down";
            const sign = (p.pl_rub || 0) >= 0 ? "+" : "";
            return `<div class="holding-row">
              <div>
                <div class="hr-name">${p.name}</div>
                <div class="hr-sub">${p.quantity} ${t("units")} · ${fmt.format(p.price_rub)} ₽</div>
              </div>
              <div>
                <div class="hr-value">${fmt.format(p.current_value_rub)} ₽</div>
                <div class="hr-gain ${dir}">${sign}${fmt.format(p.pl_rub)} ₽</div>
              </div>
            </div>`;
          }).join("");
      }

      let marketHtml = "";
      if (secs.length) {
        marketHtml = `<div class="section-title" style="margin-top:18px">${t("market")}</div>` +
          secs.map(s => {
            const selCls = s.id === selectedSecId ? " selected" : "";
            return `<div class="quote-row${selCls}" data-sec-id="${s.id}">
              <div>
                <div class="q-name">${s.name}</div>
                <div class="q-sub">${t("tap_to_trade")} →</div>
              </div>
              <div class="q-price">${fmt.format(s.price_rub)} ₽</div>
            </div>`;
          }).join("");
      } else {
        marketHtml = `<div class="empty">${t("no_securities")}</div>`;
      }

      const ticket = secs.length ? `
        <div id="trade-ticket" class="invest-panel" style="display:${selectedSecId ? 'block' : 'none'}">
          <div class="invest-panel-head">
            <span class="section-title" style="margin:0">${t("market")}</span>
            <span id="trade-sec" class="invest-panel-sel"></span>
          </div>
          <div class="side-toggle">
            <button type="button" class="side-btn buy active" data-side="buy">${t("trade_buy")}</button>
            <button type="button" class="side-btn sell" data-side="sell">${t("trade_sell")}</button>
          </div>
          <form id="trade-form" autocomplete="off">
            <div class="form-row">
              <label>${t("quantity")}</label>
              <input name="qty" type="number" min="1" step="1" placeholder="10" />
            </div>
            <div id="trade-est" class="trade-est"></div>
            <button class="btn primary" type="submit" id="trade-submit">${t("trade_buy")}</button>
          </form>
          <div id="trade-result"></div>
        </div>` : "";

      brokerageContainer.innerHTML = heroHtml + posHtml + marketHtml + ticket;

      // Select a security -> reveal ticket
      brokerageContainer.querySelectorAll(".quote-row").forEach(row => {
        row.addEventListener("click", () => {
          selectedSecId = row.dataset.secId;
          brokerageContainer.querySelectorAll(".quote-row").forEach(x => x.classList.remove("selected"));
          row.classList.add("selected");
          const sec = secs.find(s => s.id === selectedSecId);
          const secEl = document.getElementById("trade-sec");
          if (secEl && sec) secEl.textContent = `${sec.name} · ${fmt.format(sec.price_rub)} ₽`;
          const ticketEl = document.getElementById("trade-ticket");
          if (ticketEl) {
            ticketEl.style.display = "block";
            ticketEl.scrollIntoView({ behavior: "smooth", block: "center" });
          }
          updateTradeEstimate();
        });
      });

      // Buy/Sell toggle
      const submitBtn = document.getElementById("trade-submit");
      brokerageContainer.querySelectorAll(".side-btn").forEach(btn => {
        btn.addEventListener("click", () => {
          selectedSide = btn.dataset.side;
          brokerageContainer.querySelectorAll(".side-btn").forEach(b => b.classList.remove("active"));
          btn.classList.add("active");
          if (submitBtn) submitBtn.textContent = selectedSide === "buy" ? t("trade_buy") : t("trade_sell");
        });
      });

      const qtyInput = brokerageContainer.querySelector('#trade-form input[name="qty"]');
      if (qtyInput) qtyInput.addEventListener("input", updateTradeEstimate);

      const tradeForm = document.getElementById("trade-form");
      if (tradeForm) {
        tradeForm.addEventListener("submit", async (ev) => {
          ev.preventDefault();
          const tr = document.getElementById("trade-result");
          tr.innerHTML = "";
          const qty = +new FormData(ev.target).get("qty");
          if (!qty || qty <= 0) {
            tr.innerHTML = `<div class="alert error">${t("qty_required")}</div>`;
            return;
          }
          if (!selectedSecId) return;
          const sec = secs.find(s => s.id === selectedSecId);
          const notional = (sec ? sec.price_rub : 0) * qty;
          if (selectedSide === "buy" && notional > availableBalance()) {
            tr.innerHTML = `<div class="alert error">${t("insufficient_funds")}</div>`;
            return;
          }
          if (selectedSide === "sell" && qty > ownedQty(selectedSecId)) {
            tr.innerHTML = `<div class="alert error">${t("not_enough_units")}</div>`;
            return;
          }
          try {
            const picked = (secs || []).find(s => s.id === selectedSecId);
            const r = await fetch("/api/brokerage/order", {
              method: "POST", headers: {"Content-Type": "application/json"},
              body: JSON.stringify({
                client_id: d.client_id,
                security_id: selectedSecId,
                product_id: picked ? picked.product_id : undefined,
                side: selectedSide,
                quantity: qty,
              }),
            });
            const res = await r.json();
            if (r.ok && res.status === "ok") {
              const sideWord = res.side === "buy" ? t("trade_buy") : t("trade_sell");
              tr.innerHTML = `<div class="alert ok">
                ${t("order_done")}: ${sideWord} ${res.quantity} ${t("units")} ${res.security_name}<br/>
                ${fmt.format(res.price_rub)} ₽ × ${res.quantity} · ${t("commission_label")}: ${fmt.format(res.commission_rub)} ₽
                = ${fmt.format(res.total_rub)} ₽
              </div>`;
              tradeForm.reset();
              setTimeout(() => loadBrokerage(d.client_id), 500);
            } else if (r.ok && res.status === "rejected") {
              const why = res.reason === "insufficient_funds" ? t("insufficient_funds") : (res.reason || t("order_rejected"));
              tr.innerHTML = `<div class="alert error">${t("order_rejected")}: ${why}</div>`;
            } else {
              tr.innerHTML = `<div class="alert error">${res.detail || t("error")}</div>`;
            }
          } catch (e) {
            tr.innerHTML = `<div class="alert error">${t("server_down")}</div>`;
          }
        });
      }
    }

    // ---- Investments ----
    let investData = null;
    let selectedInstrumentId = null;

    function riskLabel(risk) {
      return { low: t("risk_low"), medium: t("risk_medium"), high: t("risk_high") }[risk] || risk || "";
    }

    async function loadInvest(clientId) {
      try {
        const r = await fetch(`/api/investments/${clientId}`);
        if (!r.ok) throw new Error("failed");
        investData = await r.json();
        renderInvest(investData);
      } catch(e) {
        investContainer.innerHTML = `<div class="empty">${t("invest_error")}</div>`;
      }
    }

    function renderInvest(d) {
      const instruments = d.instruments || [];
      const holdings = d.holdings || [];

      const gain = d.gain_rub || 0;
      const gainDir = gain > 0 ? "up" : gain < 0 ? "down" : "flat";
      const gainSign = gain > 0 ? "+" : "";
      const profileLine = d.investor_profile
        ? `<div class="ih-profile">${t("investor_profile_label")}: <b>${d.investor_profile}</b>${d.max_risk_level != null ? ` (max ${d.max_risk_level}/5)` : ""}</div>`
        : "";
      const heroHtml = `
        <div class="invest-hero">
          <div class="ih-label">${t("portfolio_value")}</div>
          <div class="ih-value">${fmt.format(d.total_value_rub)} ₽</div>
          <div class="ih-gain ${gainDir}">
            ${gainSign}${fmt.format(gain)} ₽ (${gainSign}${d.gain_pct}%)
          </div>
          ${profileLine}
        </div>`;

      // Existing holdings
      let holdingsHtml = "";
      if (holdings.length) {
        holdingsHtml = `<div class="section-title">${t("your_portfolio")}</div>` +
          holdings.map(h => {
            const hGain = (h.current_value_rub || 0) - (h.invested_rub || 0);
            const dir = hGain >= 0 ? "up" : "down";
            const sign = hGain >= 0 ? "+" : "";
            return `<div class="holding-row">
              <div>
                <div class="hr-name">${h.instrument_name || h.instrument_id}</div>
                <div class="hr-sub">${t("invested")}: ${fmt.format(h.invested_rub || 0)} ₽</div>
              </div>
              <div>
                <div class="hr-value">${fmt.format(h.current_value_rub || 0)} ₽</div>
                <div class="hr-gain ${dir}">${sign}${fmt.format(hGain)} ₽</div>
              </div>
            </div>`;
          }).join("");
      }

      // Available instruments
      let instrumentsHtml = "";
      if (instruments.length) {
        instrumentsHtml = `<div class="section-title" style="margin-top:18px">${t("available_instruments")}</div>` +
          instruments.map(ins => {
            const sel = ins.id === selectedInstrumentId ? "selected" : "";
            const risk = ins.risk || "medium";
            const ret = ins.expected_return_pct != null ? ins.expected_return_pct : (ins.rate_pct || "");
            const unsuit = ins.suitable === false ? " unsuitable" : "";
            const minLine = ins.min_investment_rub
              ? `<div class="in-min">${t("min_investment")}: ${fmt.format(ins.min_investment_rub)} ₽</div>`
              : "";
            const unsuitFlag = ins.suitable === false
              ? `<span class="unsuit-flag">${t("not_suitable")}</span>` : "";
            return `<div class="instrument${unsuit} ${sel}" data-instrument-id="${ins.id}">
              <div class="in-top">
                <span class="in-name">${ins.name}</span>
                <span class="in-return">${ret}% <small>${t("exp_return")}</small></span>
              </div>
              <div class="in-detail">${ins.description || ""}</div>
              ${minLine}
              <div class="in-badges">
                <span class="risk-badge ${risk}">${riskLabel(risk)}</span>
                ${unsuitFlag}
                <span class="in-cta">${t("tap_to_invest")} →</span>
              </div>
            </div>`;
          }).join("");
      } else {
        instrumentsHtml = `<div class="empty">${t("no_instruments")}</div>`;
      }

      // Invest panel (revealed + scrolled into view when an instrument is picked)
      const formHtml = instruments.length ? `
        <div id="invest-open-section" class="invest-panel" style="display:${selectedInstrumentId ? 'block' : 'none'}">
          <div class="invest-panel-head">
            <span class="section-title" style="margin:0">${t("invest_now")}</span>
            <span id="invest-panel-sel" class="invest-panel-sel"></span>
          </div>
          <form id="invest-form" autocomplete="off">
            <div class="form-row">
              <label>${t("invest_amount")}</label>
              <input name="inv_amount" type="number" min="1000" step="1000" placeholder="50 000" />
            </div>
            <button class="btn primary" type="submit">${t("invest_btn")}</button>
          </form>
          <div id="invest-result"></div>
        </div>
      ` : "";

      investContainer.innerHTML = heroHtml + holdingsHtml + instrumentsHtml + formHtml;

      // Instrument selection — reveal the invest panel and bring it into view
      investContainer.querySelectorAll(".instrument").forEach(card => {
        card.addEventListener("click", () => {
          selectedInstrumentId = card.dataset.instrumentId;
          investContainer.querySelectorAll(".instrument").forEach(c => c.classList.remove("selected"));
          card.classList.add("selected");

          const chosen = instruments.find(x => x.id === selectedInstrumentId);
          const selEl = document.getElementById("invest-panel-sel");
          if (selEl && chosen) {
            const ret = chosen.expected_return_pct != null ? ` · ${chosen.expected_return_pct}%` : "";
            selEl.textContent = chosen.name + ret;
          }
          const section = document.getElementById("invest-open-section");
          if (section) {
            section.style.display = "block";
            section.scrollIntoView({ behavior: "smooth", block: "center" });
            const amt = section.querySelector('input[name="inv_amount"]');
            if (amt) setTimeout(() => amt.focus({ preventScroll: true }), 320);
          }
        });
      });

      // Invest form handler
      const invForm = document.getElementById("invest-form");
      if (invForm) {
        invForm.addEventListener("submit", async (ev) => {
          ev.preventDefault();
          const invResult = document.getElementById("invest-result");
          invResult.innerHTML = "";
          const amount = +new FormData(ev.target).get("inv_amount");
          if (!amount || amount <= 0) {
            invResult.innerHTML = `<div class="alert error">${t("invest_fill")}</div>`;
            return;
          }
          if (!selectedInstrumentId) return;
          const picked = (d.instruments || []).find(x => x.id === selectedInstrumentId);
          if (picked && picked.min_investment_rub && amount < picked.min_investment_rub) {
            invResult.innerHTML = `<div class="alert error">${t("amount_below_min")}: ${fmt.format(picked.min_investment_rub)} ₽</div>`;
            return;
          }
          if (amount > availableBalance()) {
            invResult.innerHTML = `<div class="alert error">${t("insufficient_funds")}</div>`;
            return;
          }
          try {
            const r = await fetch("/api/invest", {
              method: "POST", headers: {"Content-Type": "application/json"},
              body: JSON.stringify({
                client_id: d.client_id,
                instrument_id: selectedInstrumentId,
                amount_rub: amount,
              }),
            });
            const res = await r.json();
            if (r.ok && res.status === "unsuitable") {
              // Regulatory suitability gate: show reasons + alternatives
              const reasons = (res.reasons || []).map(x => `<li>${x}</li>`).join("");
              let altsHtml = "";
              if ((res.suitable_alternatives || []).length) {
                altsHtml = `<div style="margin-top:10px;font-weight:600">${t("suitable_alts")}:</div>` +
                  res.suitable_alternatives.map(a =>
                    `<div style="font-size:13px;margin-top:4px">• ${a.name} — ${a.expected_return_pct}% (${t("risk_low") && a.risk_level <= 2 ? t("risk_low") : a.risk_level === 3 ? t("risk_medium") : t("risk_high")})</div>`
                  ).join("");
              }
              invResult.innerHTML = `<div class="alert info">
                <b>${t("unsuitable_title")}</b>
                <ul style="margin:8px 0 0; padding-left:18px">${reasons}</ul>
                ${altsHtml}
              </div>`;
            } else if (r.ok) {
              const proj = res.projected_value_1y_rub
                ? `<br/>${t("projected_1y")}: ${fmt.format(res.projected_value_1y_rub)} ₽`
                : "";
              const nm = res.instrument_name ? `${res.instrument_name} — ` : "";
              invResult.innerHTML = `<div class="alert ok">
                ${t("invest_success")} ${nm}${fmt.format(res.amount_rub || amount)} ₽${proj}
              </div>`;
              invForm.reset();
              setTimeout(() => loadInvest(d.client_id), 500);
            } else {
              invResult.innerHTML = `<div class="alert error">${res.detail || t("error")}</div>`;
            }
          } catch(e) {
            invResult.innerHTML = `<div class="alert error">${t("server_down")}</div>`;
          }
        });
      }
    }

    // ---- Loan products ----
    let productsData = [];
    let selectedProductId = null;

    async function loadProducts() {
      try {
        const r = await fetch("/products");
        const d = await r.json();
        productsData = (d.items || []).filter(p => p.kind === "credit" || p.kind === "loan");
        if (!productsData.length) productsData = d.items || [];
        renderProducts();
      } catch(e) {
        productList.innerHTML = `<div class="products-loading">${t("products_error")}</div>`;
      }
    }

    function renderProducts() {
      if (!productsData.length) {
        productList.innerHTML = `<div class="products-loading">${t("no_products")}</div>`;
        loanApplySection.style.display = "none";
        return;
      }
      productList.innerHTML = productsData.map(p => {
        const s = p.id === selectedProductId ? "selected" : "";
        const rateHtml = p.rate_pct != null
          ? `<span class="pc-rate">${t("rate_label")}: ${p.rate_pct}%</span>` : "";
        return `<div class="product-card ${s}" data-product-id="${p.id}">
          <div class="pc-name">${p.name}</div>
          <div class="pc-detail">${p.description || p.kind || ""}</div>
          ${rateHtml}
        </div>`;
      }).join("");
      productList.querySelectorAll(".product-card").forEach(card => {
        card.addEventListener("click", () => {
          selectedProductId = card.dataset.productId;
          productList.querySelectorAll(".product-card").forEach(c => c.classList.remove("selected"));
          card.classList.add("selected");
          loanApplySection.style.display = "block";
          loanResult.innerHTML = "";
        });
      });
    }

    // ---- Loan form ----
    const loanForm = document.getElementById("loan-form");
    loanForm.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      loanResult.innerHTML = "";
      const opt = sel.selectedOptions[0];
      if (!opt || !selectedProductId) return;
      const amount = +new FormData(ev.target).get("loan_amount");
      if (!amount || amount <= 0) {
        loanResult.innerHTML = `<div class="alert error">${t("fill_amount")}</div>`;
        return;
      }
      const payload = { client_id: opt.value, product_id: selectedProductId, amount_rub: amount };
      try {
        const r = await fetch("/api/credit-apply", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify(payload),
        });
        const d = await r.json();
        if (r.ok) {
          const isApproved = d.status === "approved";
          const icon = isApproved ? "&#10003;" : "&#10007;";
          const cls = isApproved ? "approved" : "declined";
          const status = isApproved ? t("approved") : t("declined");
          let detail = isApproved
            ? `${t("approved_detail")}: ${fmt.format(d.max_amount_rub || amount)} ₽`
            : `${t("declined_detail")}`;
          if (d.reason) detail += `<br/>${t("reason_label")}: ${d.reason}`;
          loanResult.innerHTML = `<div class="decision-box ${cls}">
            <div class="decision-icon">${icon}</div>
            <div class="decision-status">${status}</div>
            <div class="decision-detail">${detail}</div>
          </div>`;
        } else {
          loanResult.innerHTML = `<div class="alert error">${d.detail || t("error")}</div>`;
        }
      } catch(e) {
        loanResult.innerHTML = `<div class="alert error">${t("server_down")}</div>`;
      }
    });

    loadClients();
    loadProducts();
    applyLang();
  })();
  
