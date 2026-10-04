// Page-free report rules returning {kind, code, ...context}; twins in report_service, cases in tests.test_rule_cases.
(() => {
  "use strict";

  const asString = value => typeof value === "string" ? value : "";

  // Python's str.strip(): String.prototype.trim also strips U+FEFF but keeps U+001C-U+001F and U+0085.
  const strip = text => text.replace(/^[\t-\r\x1c-\x20\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+|[\t-\r\x1c-\x20\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/g, "");

  // Letters and digits by the browser's own Unicode categories, as Setup has always judged them.
  const invalidCharacters = (value, rule) => [...new Set([...value].filter(character => !(
    (rule.letters && /\p{L}/u.test(character))
    || (rule.numbers && /\p{Nd}/u.test(character))
    || (rule.spaces && character === " ")
    || (rule.line_breaks && (character === "\r" || character === "\n"))
    || rule.symbols.includes(character)
  )))];

  const scopeBoxText = raw => [typeof raw === "string" ? raw : asString(raw?.component), asString(raw?.description)];

  // Twin of report_service.WORD_REFUSED_CHARACTERS: outside XML 1.0's Char production, so Word cannot store them.
  const wordRefused = character => /[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]/.test(character)
    || (character.length === 1 && character.charCodeAt(0) >= 0xd800 && character.charCodeAt(0) <= 0xdfff);
  const inRanges = (character, ranges) => {
    const codePoint = character.codePointAt(0);
    return (ranges || []).some(([first, last]) => codePoint >= first && codePoint <= last);
  };

  // Twin of report_service.scope_value_refusals.
  const scopeValueRefusals = (environment, channel, line, component, description, vocabulary) => {
    const entry = (box, text, limit) => {
      const context = {field:"scope", environment, app_type:channel, box, line};
      const results = [];
      const characters = [...new Set([...text].filter(wordRefused))];
      if (characters.length) results.push({kind:"refusal", code:"invalid_characters", ...context, characters});
      if (tooLong(text, limit)) results.push({kind:"refusal", code:"too_long", ...context, limit});
      return results;
    };
    const limits = vocabulary.scope_limits;
    if (!vocabulary.component_channels.includes(channel)) return entry("component", component, limits.line);
    return [...entry("component", component, limits.component), ...entry("description", description, limits.description)];
  };

  // Twin of report_service.scope_box_refusals.
  const scopeBoxRefusals = (environment, channel, componentText, descriptionText, vocabulary) => {
    const components = componentText.split("\n");
    const descriptions = descriptionText.split("\n");
    const named = [];
    for (let line = 0; line < Math.max(components.length, descriptions.length); line += 1) {
      const component = strip(components[line] || "");
      if (component && !component.startsWith("#")) named.push({line, component, description:strip(descriptions[line] || "")});
    }
    const results = [];
    if (vocabulary.component_channels.includes(channel)) {
      const seen = new Set();
      const repeated = [];
      named.forEach(({component}) => {
        if (seen.has(component) && !repeated.includes(component)) repeated.push(component);
        seen.add(component);
      });
      results.push(...repeated.map(component => ({kind:"refusal", code:"duplicate_component", environment, app_type:channel, component})));
    }
    named.forEach(({line, component, description}) => results.push(...scopeValueRefusals(environment, channel, line, component, description, vocabulary)));
    return results;
  };

  // Twin of report_service.scope_text_refusals.
  const scopeRefusals = (report, vocabulary) => {
    const engagement = report?.engagement || {};
    const testedChannels = engagement.tested_channels || [];
    if (!testedChannels.length) return [{kind:"refusal", code:"no_app_type"}];
    const covered = vocabulary.channels.map(([channel]) => channel).filter(channel => testedChannels.includes(channel));
    return (engagement.tested_environments || []).flatMap(environment => covered.flatMap(channel =>
      scopeBoxRefusals(environment, channel, ...scopeBoxText(report?.scope_text?.[environment]?.[channel]), vocabulary)));
  };

  // Twin of report_service.scope_text_targets; paired by raw index before cleaning, as reconcile_targets does.
  const scopeTargets = (report, vocabulary) => {
    const engagement = report?.engagement || {};
    const testedChannels = engagement.tested_channels || [];
    const covered = vocabulary.channels.map(([channel]) => channel).filter(channel => testedChannels.includes(channel));
    const targets = [];
    (engagement.tested_environments || []).forEach(environment => {
      covered.forEach(channel => {
        const raw = report?.scope_text?.[environment]?.[channel];
        const [componentText, descriptionText] = scopeBoxText(raw);
        const components = componentText.split("\n");
        const descriptions = descriptionText.split("\n");
        const seen = new Set();
        for (let index = 0; index < Math.max(components.length, descriptions.length); index += 1) {
          const component = strip(components[index] || "");
          if (!component || component.startsWith("#") || seen.has(component)) continue;
          seen.add(component);
          targets.push({environment, app_type:channel, component, description:strip(descriptions[index] || "")});
        }
      });
    });
    return targets;
  };

  // Twin of report_service.USERNAME_PATTERN, which the vocabulary does not serve.
  const USERNAME_PATTERN = /^[A-Za-z0-9._@\\-](?:[ A-Za-z0-9._@\\-]*[A-Za-z0-9._@\\-])?$/;

  // In UTF-16 units, which is what length and maxlength count. Twin: report_service.text_length.
  const tooLong = (value, limit) => limit != null && value.length > limit;

  // What a save says about one username, in order: invalid characters or a space at either end, then length.
  const usernameRefusals = (username, vocabulary) => {
    if (!username || username === "N/A") return [];
    const rule = vocabulary.character_rules.username;
    const results = [];
    if (!USERNAME_PATTERN.test(username)) {
      const characters = invalidCharacters(username, rule);
      results.push(characters.length ? {code:"invalid_characters", field:"username", characters} : {code:"invalid_username"});
    }
    if (tooLong(username, rule.max_length)) results.push({code:"too_long", field:"username", limit:rule.max_length});
    return results;
  };

  // Twin of report_service.setup_field_refusals.
  const fieldRefusals = (engagement, vocabulary) => {
    const results = [];
    const refuse = (code, context = {}) => results.push({kind:"refusal", code, ...context});
    const check = (field, value, context = {}) => {
      if (typeof value !== "string" || !value) return;
      const rule = vocabulary.character_rules[field];
      const characters = invalidCharacters(value, rule);
      if (characters.length) refuse("invalid_characters", {field, ...context, characters});
      if (tooLong(value, rule.max_length)) refuse("too_long", {field, ...context, limit:rule.max_length});
    };
    ["app_name", "ci_number", "bsn_number", "app_owner", "tester"].forEach(field => check(field, engagement[field]));
    const environments = engagement.tested_environments || [];
    environments.forEach(environment => {
      const testWindow = engagement.test_windows?.[environment];
      if (!testWindow || typeof testWindow !== "object" || Array.isArray(testWindow)) return;
      const {start_date:start, end_date:end} = testWindow;
      if (typeof start === "string" && typeof end === "string" && start && end && start > end) refuse("test_dates_out_of_order", {environment});
      check("test_time", testWindow.test_time, {environment});
    });
    const accounts = engagement.test_accounts || [];
    if (accounts.length > vocabulary.max_test_accounts) refuse("too_many_accounts", {limit:vocabulary.max_test_accounts});
    accounts.forEach((account, index) => {
      if (!account || typeof account !== "object" || Array.isArray(account)) return;
      check("user_role", account.user_role, {account:index + 1});
      usernameRefusals(typeof account.username === "string" ? account.username : "", vocabulary)
        .forEach(({code, ...context}) => refuse(code, {...context, account:index + 1}));
    });
    check("limitations", engagement.limitations);
    // Stripped as the model's strip_label does before the save checks it.
    if (environments.includes("non_production")) check("non_production_label", typeof engagement.non_production_label === "string" ? strip(engagement.non_production_label) : engagement.non_production_label);
    return results;
  };

  const setupResults = (report, vocabulary) => {
    const engagement = report?.engagement || {};
    const results = [...scopeRefusals(report, vocabulary), ...fieldRefusals(engagement, vocabulary)];
    const issue = (code, context = {}) => results.push({kind:"issue", code, ...context});
    if (!strip(asString(engagement.app_name))) issue("missing_app_name");
    if (!engagement.segment) issue("missing_segment");
    if (!engagement.report_type) issue("missing_report_type");
    if (!engagement.network) issue("missing_network");
    if (!strip(asString(engagement.tester))) issue("missing_tester");
    if (!engagement.report_date) issue("missing_report_date");
    const environments = engagement.tested_environments || [];
    if (!environments.length) issue("no_tested_environment");
    const testedChannels = engagement.tested_channels || [];
    const coveredComponents = vocabulary.component_channels.filter(channel => testedChannels.includes(channel));
    if (coveredComponents.length > 1) issue("mobile_and_thick_client", {app_types:coveredComponents});
    const targets = scopeTargets(report, vocabulary);
    environments.forEach(environment => {
      const testWindow = engagement.test_windows?.[environment] || {};
      if (!testWindow.start_date || !testWindow.end_date) issue("missing_test_dates", {environment});
      const named = targets.filter(target => target.environment === environment);
      if (!named.length) issue("missing_scope_target", {environment});
      named.filter(target => vocabulary.component_channels.includes(target.app_type) && !target.description)
        .forEach(({app_type, component}) => issue("missing_component_description", {environment, app_type, component}));
    });
    // Twin of the account loop in report_service.setup_results.
    const firstRow = new Map();
    (engagement.test_accounts || []).forEach((account, index) => {
      if (!account || typeof account !== "object" || Array.isArray(account)) return;
      const role = strip(asString(account.user_role));
      const username = strip(asString(account.username));
      if (!role && !username) return;
      const key = JSON.stringify([role, username]);
      if (!username) issue("incomplete_test_account", {account:index + 1, missing:"username"});
      else if (!role) issue("incomplete_test_account", {account:index + 1, missing:"user_role"});
      else if (firstRow.has(key)) issue("repeated_test_account", {account:index + 1, first:firstRow.get(key)});
      else firstRow.set(key, index + 1);
    });
    return results;
  };

  const formatRuleMessage = (result, report, vocabulary, {scopeContext = false} = {}) => {
    const fixedMessages = {
      missing_app_name:"Enter the application name.",
      missing_segment:"Choose a segment.",
      missing_report_type:"Choose a report type.",
      missing_network:"Choose the network access.",
      missing_tester:"Enter the tester's name.",
      missing_report_date:"Enter the report date.",
      no_tested_environment:"Choose at least one environment to test.",
      no_app_type:"Choose at least one app type.",
    };
    if (result.code in fixedMessages) return fixedMessages[result.code];
    if (result.code === "too_many_accounts") {
      return `A report can list at most ${result.limit} test accounts. Remove some.`;
    }
    if (result.code === "mobile_and_thick_client") {
      const labels = result.app_types.map(channel => vocabulary.channels.find(([value]) => value === channel)?.[1]);
      return `Choose ${labels.join(" or ")}, not both.`;
    }
    if (result.code === "repeated_test_account") {
      return `Test account ${result.account} is the same as test account ${result.first}. Remove one of them.`;
    }
    if (result.code === "missing_test_dates") {
      const environment = result.environment === "production" ? "Production" : "Non-Production";
      const window = report?.engagement?.test_windows?.[result.environment] || {};
      const missing = ["start", "end"].filter(name => !window[`${name}_date`]);
      const dates = missing.length === 2 ? "start and end dates" : `${missing[0]} date`;
      return `Enter the ${environment} ${dates}.`;
    }
    if (result.code === "missing_scope_target") {
      return `Add a scope target for ${result.environment === "production" ? "Production" : "Non-Production"}.`;
    }
    if (result.code === "missing_component_description") {
      const scope = report?.scope_text?.[result.environment]?.[result.app_type] || "";
      const text = typeof scope === "object" ? scope.component || "" : scope;
      const row = text.split("\n").findIndex(component => component.trim() === result.component) + 1;
      return `Enter a description for component ${row}.`;
    }
    if (result.code === "incomplete_test_account") {
      const detail = result.missing === "username" ? "username" : "user role";
      const other = result.missing === "username" ? "user role" : "username";
      return `Enter a ${detail} for test account ${result.account}, or clear its ${other}.`;
    }
    if (result.code === "invalid_username") {
      const username = result.value ?? report?.engagement?.test_accounts?.[result.account - 1]?.username ?? "";
      const starts = username.startsWith(" ");
      const ends = username.endsWith(" ");
      const position = starts && ends ? "starts and ends" : starts ? "starts" : "ends";
      return `${result.label || `Username ${result.account}`} ${position} with a space. Delete ${starts && ends ? "them" : "it"}.`;
    }
    if (result.code === "test_dates_out_of_order") {
      const environment = result.environment === "production" ? "Production" : "Non-Production";
      return `${environment} start date is after its end date. Change one of them.`;
    }
    if (result.code === "duplicate_component") {
      const scope = report?.scope_text?.[result.environment]?.[result.app_type] || "";
      const text = typeof scope === "object" ? scope.component || "" : scope;
      const seen = new Map();
      let first = 0;
      let row = 0;
      text.split("\n").forEach((component, index) => {
        component = component.trim();
        if (component !== result.component) return;
        if (seen.has(component) && !row) { first = seen.get(component); row = index + 1; }
        else if (!seen.has(component)) seen.set(component, index + 1);
      });
      const message = `Component ${row} is the same as component ${first}. Remove one of them.`;
      if (!scopeContext) return message;
      const environment = result.environment === "production" ? "Production" : "Non-Production";
      const channel = vocabulary.channels.find(([value]) => value === result.app_type)?.[1] || result.app_type;
      return `In the ${environment} ${channel} scope, ${message}`;
    }
    if (result.code === "too_long") {
      const field = result.field;
      const rule = vocabulary.character_rules[field];
      let label = result.label || rule?.label || "Scope target";
      let value = result.value ?? report?.engagement?.[field] ?? "";
      if (field === "test_time") {
        value = result.value ?? report?.engagement?.test_windows?.[result.environment]?.test_time ?? "";
        label = `${result.environment === "production" ? "Production" : "Non-Production"} time`;
      } else if (result.account) {
        value = result.value ?? report?.engagement?.test_accounts?.[result.account - 1]?.[field] ?? "";
        label = `${label} ${result.account}`;
      } else if (field === "scope") {
        const scope = report?.scope_text?.[result.environment]?.[result.app_type] || "";
        const boxValue = result.box === "description" && typeof scope === "object" ? scope.description || "" : typeof scope === "object" ? scope.component || "" : scope;
        value = result.value ?? boxValue.split("\n")[result.line] ?? "";
        const environment = result.environment === "production" ? "Production" : "Non-Production";
        const channel = vocabulary.channels.find(([value]) => value === result.app_type)?.[1] || result.app_type;
        label = scopeContext ? `In the ${environment} ${channel} scope, line ${result.line + 1}` : `Line ${result.line + 1}`;
      }
      return `${label} has ${[...value].length} characters. Shorten it to ${result.limit} or fewer.`;
    }
    if (result.code === "invalid_characters") {
      const field = result.field;
      const rule = vocabulary.character_rules[field];
      const hiddenRanges = vocabulary.unicode_character_ranges?.hidden;
      const label = result.label || rule?.label || "Scope target";
      let value = result.value ?? report?.engagement?.[field] ?? "";
      let fieldLabel = label;
      if (field === "test_time") {
        value = result.value ?? report?.engagement?.test_windows?.[result.environment]?.test_time ?? "";
        fieldLabel = `${result.environment === "production" ? "Production" : "Non-Production"} time`;
      } else if (result.account) {
        value = result.value ?? report?.engagement?.test_accounts?.[result.account - 1]?.[field] ?? "";
        fieldLabel = `${label} ${result.account}`;
      } else if (field === "scope") {
        const scope = report?.scope_text?.[result.environment]?.[result.app_type] || "";
        const boxValue = result.box === "description" && typeof scope === "object" ? scope.description || "" : typeof scope === "object" ? scope.component || "" : scope;
        value = result.value ?? boxValue.split("\n")[result.line] ?? "";
        const environment = result.environment === "production" ? "Production" : "Non-Production";
        const channel = vocabulary.channels.find(([value]) => value === result.app_type)?.[1] || result.app_type;
        fieldLabel = scopeContext ? `In the ${environment} ${channel} scope, line ${result.line + 1}` : `Line ${result.line + 1}`;
      }
      for (const [index, character] of [...value].entries()) {
        if (result.characters.includes(character) && ((inRanges(character, hiddenRanges) && character !== " ") || wordRefused(character))) {
          const before = [...value].slice(0, index);
          const context = before.length ? `${before.length > 12 ? "..." : ""}${before.slice(-12).join("")}` : null;
          const detail = character === "\t" ? "a tab" : character === "\n" || character === "\r" ? "a line break" : character === "\u00a0" ? "a non-breaking space" : "a hidden character";
          return `${fieldLabel} has ${detail} ${context === null ? "at the start" : `after ${JSON.stringify(context)}`}. Delete it.`;
        }
      }
      if (rule && result.characters.length === 1 && result.characters[0] === " " && !rule.spaces) {
        const plural = value.split(" ").length - 1 > 1;
        return `${label} cannot have spaces. Remove ${plural ? "the spaces" : "the space"}.`;
      }
      const quoted = result.characters.map(character => JSON.stringify(character));
      if (quoted.length === 1) return `${label} cannot have ${quoted[0]}. Remove or replace it.`;
      return `${label} cannot have ${quoted.slice(0, -1).join(", ")} or ${quoted.at(-1)}. Remove or replace them.`;
    }
    throw new Error(`Unknown rule message: ${result.code}`);
  };

  window.vrRules = {setupResults, scopeTargets, scopeRefusals, invalidCharacters, strip, usernameRefusals, tooLong, formatRuleMessage};
})();
