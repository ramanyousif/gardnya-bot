# ═══════════════════════════════════════════════════════════════════════════════
#  بوتی گاردنیا - بەڕێوەبەر و ژیریی دەستکردی تیلیگرام (Gardnya Security & AI Bot)
# ═══════════════════════════════════════════════════════════════════════════════

param(
    [string]$ConfigPath = ".\config.json"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# ═══════════════════════════════════════════════════════════════════════════════
#  بەشی ١: فەنکشنە یاریدەدەرەکان
# ═══════════════════════════════════════════════════════════════════════════════

function ConvertTo-Hashtable {
    param([Parameter(ValueFromPipeline)]$InputObject)
    process {
        if ($null -eq $InputObject) { return $null }
        if ($InputObject -is [System.Collections.IDictionary]) {
            $hash = @{}
            foreach ($key in $InputObject.Keys) { $hash[$key] = ConvertTo-Hashtable $InputObject[$key] }
            return $hash
        }
        if ($InputObject -is [System.Collections.IEnumerable] -and $InputObject -isnot [string]) {
            $list = @()
            foreach ($item in $InputObject) { $list += ConvertTo-Hashtable $item }
            return $list
        }
        if ($InputObject -is [pscustomobject]) {
            $hash = @{}
            foreach ($property in $InputObject.PSObject.Properties) { $hash[$property.Name] = ConvertTo-Hashtable $property.Value }
            return $hash
        }
        return $InputObject
    }
}

function Read-JsonFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return @{} }
    $content = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    if ([string]::IsNullOrWhiteSpace($content)) { return @{} }
    return ConvertTo-Hashtable ($content | ConvertFrom-Json)
}

function Write-JsonFile {
    param([string]$Path, [hashtable]$Value)
    $directory = Split-Path -Parent $Path
    if ($directory -and -not (Test-Path -LiteralPath $directory)) { New-Item -ItemType Directory -Path $directory -Force | Out-Null }
    $Value | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Initialize-Map {
    param([hashtable]$Map, [string]$Key)
    if ($null -eq $Map) { return $null }
    if (-not $Map.ContainsKey($Key) -or $null -eq $Map[$Key]) { $Map[$Key] = @{} }
    return $Map[$Key]
}

function Get-UnixTime { return [int][DateTimeOffset]::UtcNow.ToUnixTimeSeconds() }

function Get-RandomItem {
    param([array]$Items)
    if ($null -eq $Items -or $Items.Count -eq 0) { return $null }
    return $Items[(Get-Random -Minimum 0 -Maximum $Items.Count)]
}

# ═══════════════════════════════════════════════════════════════════════════════
#  بەشی ٢: ڕێکخستن و یاساکان
# ═══════════════════════════════════════════════════════════════════════════════

$Config = @{
    token                       = $env:TELEGRAM_BOT_TOKEN
    botUsername                  = "gardny4_bot"
    groqApiKey                  = $env:GROQ_API_KEY
    groqModel                   = "llama-3.3-70b-versatile"
    aiEnabled                   = $true
    aiInPrivateChats            = $true
    aiHistoryMessages           = 10
    aiSystemPrompt              = @"
You are Gardnya (گاردنیا), a friendly, highly intelligent Kurdish assistant and companion in a Telegram group chat.
You speak only in short, natural, human Sorani Kurdish (کوردیی سۆرانی ئاسایی چات).

Strict Rules:
1. NEVER translate machine English into Kurdish. Never use broken literal dictionary words.
2. Respond in 1 short, natural sentence as a real Kurdish friend in chat.
3. Use everyday Kurdish chat phrases (وەڵا, گیان, کاکە, ئاساییە, عافیەت بێت, دەستخۆش, هههه).
4. Be witty, friendly, respectful, and helpful.
"@
    blockPhotos                 = $true
    blockVideos                 = $true
    blockGIFs                   = $true
    blockStickers               = $true
    blockLinks                  = $true
    blockBadWords               = $true
    maxWarnings                 = 3
    autoMuteMinutes             = 60
}

if (Test-Path -LiteralPath $ConfigPath) {
    $fileConfig = Read-JsonFile $ConfigPath
    foreach ($key in $fileConfig.Keys) { $Config[$key] = $fileConfig[$key] }
}

if ([string]::IsNullOrWhiteSpace($Config.token) -or $Config.token -eq "PUT_YOUR_BOTFATHER_TOKEN_HERE") {
    throw "Token دیاری نەکراوە! تکایە لەناو config.json یان TELEGRAM_BOT_TOKEN دابنێ."
}

# ───── 🌸 بەخێرهاتنی ئەندامانی نوێ ─────
$WelcomeMessages = @(
    "🌸 سڵاو {name} گیان! زۆر بەخێر هاتیت بۆ گروپەکەمان 🎉`n`nگەرمترین بەخێرهاتنت لێ دەکەین، هیواداریین کاتێکی زۆر خۆش و بەسوود لەگەڵمان بەسەر بەریت! ✨❤️"
    "👑 سڵاو لە {name} خۆشەویست! زۆر بەخێربێیت بۆ نێو خێزانە چاک و ئازیزەکەمان 🌟`n`nخۆشحاڵین بە هاتنت، بە هیوای کاتی خۆش و سەرکەوتووانە! 🌺"
    "✨ سڵاو و دەرەکەت خۆش {name} گیان! بەخێربێیت بەسەر چاوانمان 💐`n`nگروپ بە هاتنی تۆ ڕووناک بووەوە! 🎉"
)

# ───── 💬 جوابی ئامادەکراوی کوردی ─────
$SmartReplies = @(
    @{
        patterns = @("سڵاو", "سلاو", "سلام", "هەڵۆ", "hello", "hi", "slaw")
        replies  = @("سڵاو لە تۆش گیان! ❤️", "سڵاو بەخێر بێیت! 🌸", "سڵاو چۆنیت؟ 😊", "سڵاو و ڕێز بۆ تۆی بەڕێز 💖")
    },
    @{
        patterns = @("چۆنیت", "چونیت", "چۆنی", "چاکیت", "باشیت", "چ هەواڵ", "choni")
        replies  = @("سوپاس بۆ خوا من زۆر باشم، تۆ چۆنیت گیان؟ ✨", "زۆر باشم سوپاس! تۆ بڵێ چی هەیە؟ 😊", "سوپاس گەورەم، من باشم تۆ چۆنیت؟ ❤️")
    },
    @{
        patterns = @("دەستت خۆش", "دەست خۆش", "دەستت کەڵەک پێ بێت", "دەستت ڕەنگین", "dast xosh")
        replies  = @("عافیەتت بێت گیانەکەم! ❤️", "سەرکەوتوو بیت، شایەنی نییە 🌸", "دەستی تۆش خۆش بێت براکەم ✨")
    },
    @{
        patterns = @("سوپاس", "سوپاست دەکەم", "دەستت خۆش بیت", "spas", "supas")
        replies  = @("شایەنی نییە گیانەکەم! ❤️", "بەردەوام لە خزمەتین! 🌸", "سەرچاوم! ✨")
    },
    @{
        patterns = @("ناوی تۆ چییە", "ناوت چییە", "تۆ کێیت", "کێیت", "nawt chya")
        replies  = @("من ناوم گاردنیایە! بوتی پاراستن و ژیریی دەستکرد لەم گروپەدا 🤖🌸", "من گاردنیام! خزمەتکاری ئێوەی ئازیز ❤️")
    },
    @{
        patterns = @("گاردنیا", "gardnya", "بووت", "بوت")
        replies  = @("گیانی گاردنیا، فەرموو لە خزمەتدام! 🌸", "بەڵێ گیان، چۆن دەتوانم یارمەتیت بدەم؟ ✨", "سەرچاو لە خزمەتتام! 💖")
    }
)

# ───── 🛡️ فیلتەری جنێو و قسەی ناشرین ─────
$BadWordsList = @(
    'قن', 'قنت', 'قنم', 'قنی', 'قوز', 'قۆز', 'قوزت', 'قوزم', 'قوزی',
    'کیر', 'کێرم', 'کیرم', 'کێر', 'کێری', 'کێرت', 'کیرت',
    'گواو', 'گوخۆر', 'گوو', 'گو', 'گوت', 'گووم',
    'حیز', 'سۆزانی', 'سێکس', 'پۆرن', 'قەحبە', 'گەواد', 'پینتی', 'بێنامووس', 'نامووس',
    'ئەتگێم', 'ئەگێم', 'بگێم', 'بگێرم',
    'fuck', 'f\s*u\s*c\s*k', 'shit', 'bitch', 'asshole', 'dick', 'pussy',
    'bastard', 'whore', 'slut', 'nigger', 'faggot', 'cock', 'cunt',
    'motherf', 'stfu', 'porn', 'xxx', 'nude', 'naked',
    'boobs', 'tits', 'penis', 'vagina', 'orgasm', 'hentai'
)

$BadPhrasesList = @(
    'لە\s*دایکت', 'دایکت\s*بگێم', 'دایکت\s*گێم', 'دایکت\s*بێ', 'دایکت\s*بم',
    'لە\s*خوشکت', 'خوشکت\s*بگێم', 'خوشکت\s*گێم', 'خوشکت\s*بێ', 'خوشکت\s*بم',
    'لە\s*عەرزت', 'لە\s*قەبرت', 'داپیرەت\s*بم'
)

# ═══════════════════════════════════════════════════════════════════════════════
#  بەشی ٣: داتا و پەیوەندی Telegram
# ═══════════════════════════════════════════════════════════════════════════════

$ApiBase = "https://api.telegram.org/bot$($Config.token)"
$StatePath = ".\data\state.json"
$State = Read-JsonFile $StatePath
if (-not $State.ContainsKey("warnings")) { $State["warnings"] = @{} }
if (-not $State.ContainsKey("rules")) { $State["rules"] = @{} }
if (-not $State.ContainsKey("aiHistory")) { $State["aiHistory"] = @{} }

function Save-State { Write-JsonFile $StatePath $script:State }

function Invoke-Telegram {
    param([string]$Method, [hashtable]$Body = @{})
    $uri = "$script:ApiBase/$Method"
    try {
        $json = $Body | ConvertTo-Json -Depth 20
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
        return Invoke-RestMethod -Uri $uri -Method Post -ContentType "application/json; charset=utf-8" -Body $bytes
    } catch {
        Write-Warning "Telegram: $($_.Exception.Message)"
        return $null
    }
}

$script:BotId = 0
$meRes = Invoke-Telegram "getMe"
if ($null -ne $meRes -and $meRes.ok) {
    $script:BotId = [Int64]$meRes.result.id
    Write-Host "Bot authenticated: @$($meRes.result.username)" -ForegroundColor Green
}

function Send-TgMessage {
    param([Int64]$ChatId, [string]$Text, [int]$ReplyTo = 0, [bool]$Preview = $false)
    $body = @{ chat_id = $ChatId; text = $Text; disable_web_page_preview = (-not $Preview) }
    if ($ReplyTo -gt 0) {
        $body["reply_to_message_id"] = $ReplyTo
        $body["allow_sending_without_reply"] = $true
    }
    Invoke-Telegram "sendMessage" $body | Out-Null
}

function Remove-TgMessage {
    param([Int64]$ChatId, [int]$MessageId)
    Invoke-Telegram "deleteMessage" @{ chat_id = $ChatId; message_id = $MessageId } | Out-Null
}

function Get-DisplayName {
    param([hashtable]$User)
    if ($null -eq $User) { return "?" }
    if (-not [string]::IsNullOrWhiteSpace($User["first_name"])) { return $User["first_name"] }
    if (-not [string]::IsNullOrWhiteSpace($User["username"])) { return "@$($User["username"])" }
    return [string]$User["id"]
}

function Test-IsAdmin {
    param([Int64]$ChatId, [Int64]$UserId)
    $res = Invoke-Telegram "getChatMember" @{ chat_id = $ChatId; user_id = $UserId }
    if ($null -ne $res -and $res.ok) {
        $status = [string]$res.result.status
        return ($status -eq "creator" -or $status -eq "administrator")
    }
    return $false
}

function Add-UserWarning {
    param([Int64]$ChatId, [Int64]$UserId)
    $cKey = [string]$ChatId; $uKey = [string]$UserId
    $wMap = Initialize-Map $script:State["warnings"] $cKey
    $current = 0
    if ($wMap.ContainsKey($uKey)) { $current = [int]$wMap[$uKey] }
    $current++
    $wMap[$uKey] = $current
    Save-State
    return $current
}

function Reset-UserWarnings {
    param([Int64]$ChatId, [Int64]$UserId)
    $cKey = [string]$ChatId; $uKey = [string]$UserId
    if ($script:State["warnings"].ContainsKey($cKey)) {
        $script:State["warnings"][$cKey].Remove($uKey)
        Save-State
    }
}

function Set-UserMute {
    param([Int64]$ChatId, [Int64]$UserId, [int]$Minutes)
    $until = (Get-UnixTime) + ($Minutes * 60)
    Invoke-Telegram "restrictChatMember" @{
        chat_id = $ChatId; user_id = $UserId; until_date = $until
        permissions = @{
            can_send_messages = $false
            can_send_media_messages = $false
            can_send_other_messages = $false
            can_add_web_page_previews = $false
        }
    } | Out-Null
}

function Set-UserUnmute {
    param([Int64]$ChatId, [Int64]$UserId)
    Invoke-Telegram "restrictChatMember" @{
        chat_id = $ChatId; user_id = $UserId
        permissions = @{
            can_send_messages = $true
            can_send_media_messages = $true
            can_send_other_messages = $true
            can_add_web_page_previews = $true
        }
    } | Out-Null
}

function Remove-UserFromChat {
    param([Int64]$ChatId, [Int64]$UserId)
    Invoke-Telegram "banChatMember" @{ chat_id = $ChatId; user_id = $UserId } | Out-Null
}

function Restore-UserToChat {
    param([Int64]$ChatId, [Int64]$UserId)
    Invoke-Telegram "unbanChatMember" @{ chat_id = $ChatId; user_id = $UserId; only_if_banned = $true } | Out-Null
}

# ═══════════════════════════════════════════════════════════════════════════════
#  بەشی ٤: مۆتۆری ژیریی دەستکرد (Groq AI Engine)
# ═══════════════════════════════════════════════════════════════════════════════

function Invoke-CleanAIAnswer {
    param([string]$Text)
    if ([string]::IsNullOrWhiteSpace($Text)) { return "" }
    $clean = $Text -replace '(?im)^\s*@?[a-zA-Z0-9_]+:\s*', ''
    $clean = $clean -replace '(?im)^\s*(system note|translation note|note|translation)\s*[::-].*$', ''
    $clean = $clean -replace '\([^()\r\n]*\)', ''
    $clean = $clean -replace '[()]', ''
    if ($clean -match '[\u0900-\u097F]') { return "" }
    $clean = ($clean -split "`r?`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ }) -join "`n"
    return $clean.Trim()
}

function Invoke-GroqReply {
    param([string]$SystemPrompt, [array]$History, [string]$Question)
    $apiKey = [string]$script:Config.groqApiKey
    $model = [string]$script:Config.groqModel
    if ([string]::IsNullOrWhiteSpace($model)) { $model = "llama-3.3-70b-versatile" }

    $messages = @(@{ role = "system"; content = $SystemPrompt })
    foreach ($item in $History) {
        if ($item -is [System.Collections.IDictionary] -and $item.Contains("role") -and $item.Contains("content")) {
            $messages += @{ role = [string]$item["role"]; content = [string]$item["content"] }
        }
    }
    $messages += @{ role = "user"; content = $Question }

    $bodyObj = @{ model = $model; messages = $messages; max_tokens = 120; temperature = 0.5 }
    $jsonStr = $bodyObj | ConvertTo-Json -Depth 20
    $bodyBytes = [System.Text.Encoding]::UTF8.GetBytes($jsonStr)

    $uri = "https://api.groq.com/openai/v1/chat/completions"
    $req = [System.Net.HttpWebRequest]::Create($uri)
    $req.Method = "POST"
    $req.Timeout = 30000
    $req.ContentType = "application/json; charset=utf-8"
    $req.Headers.Add("Authorization", "Bearer $apiKey")
    $req.ContentLength = $bodyBytes.Length

    $stream = $req.GetRequestStream()
    $stream.Write($bodyBytes, 0, $bodyBytes.Length)
    $stream.Close()

    $resp = $req.GetResponse()
    $reader = New-Object System.IO.StreamReader($resp.GetResponseStream(), [System.Text.Encoding]::UTF8)
    $respStr = $reader.ReadToEnd()
    $reader.Close()
    $resp.Close()

    if ([string]::IsNullOrWhiteSpace($respStr)) { return "" }
    $parsed = $respStr | ConvertFrom-Json
    if ($parsed.choices -and $parsed.choices.Count -gt 0 -and $parsed.choices[0].message) {
        return [string]$parsed.choices[0].message.content
    }
    return ""
}

function Get-SmartReply {
    param([string]$Text)
    if ([string]::IsNullOrWhiteSpace($Text)) { return $null }
    $lower = $Text.Trim().ToLowerInvariant()

    foreach ($entry in $script:SmartReplies) {
        foreach ($pattern in $entry.patterns) {
            if ($lower -match [regex]::Escape($pattern)) {
                return Get-RandomItem $entry.replies
            }
        }
    }
    return $null
}

function Get-AIReply {
    param([Int64]$ChatId, [Int64]$UserId, [string]$Question)
    if (-not [bool]$script:Config.aiEnabled) { return "" }

    $smart = Get-SmartReply $Question
    if (-not [string]::IsNullOrWhiteSpace($smart)) {
        return $smart
    }

    $historyKey = "$($ChatId):$($UserId)"
    $history = @()
    if ($script:State["aiHistory"].ContainsKey($historyKey) -and $null -ne $script:State["aiHistory"][$historyKey]) {
        $history = @($script:State["aiHistory"][$historyKey])
    }
    $sysPrompt = [string]$script:Config.aiSystemPrompt
    $answer = ""

    if (-not [string]::IsNullOrWhiteSpace($script:Config.groqApiKey)) {
        try {
            $answer = Invoke-GroqReply $sysPrompt $history $Question
            $answer = Invoke-CleanAIAnswer $answer
        } catch {
            Write-Warning "Groq: $($_.Exception.Message)"
            $answer = ""
        }
    }

    if ([string]::IsNullOrWhiteSpace($answer)) {
        return "گیان دەتوانیت دووبارە ڕوونی بکەیتەوە؟ 😅"
    }

    $history += @(@{ role = "user"; content = $Question }, @{ role = "assistant"; content = $answer })
    $maxItems = [Math]::Max(2, [int]$script:Config.aiHistoryMessages)
    if ($history.Count -gt $maxItems) { $script:State["aiHistory"][$historyKey] = @($history | Select-Object -Last $maxItems) }
    else { $script:State["aiHistory"][$historyKey] = @($history) }
    try { Save-State } catch { }

    return $answer
}

# ═══════════════════════════════════════════════════════════════════════════════
#  بەشی ٥: فیلتەرەکانی ئاسایش
# ═══════════════════════════════════════════════════════════════════════════════

function Test-ContainsBadWord {
    param([string]$Text)
    if ([string]::IsNullOrWhiteSpace($Text)) { return $false }
    $cleanText = $Text.ToLowerInvariant()
    
    foreach ($p in $script:BadWordsList) {
        if ($cleanText -match [regex]::Escape($p)) { return $true }
    }

    foreach ($phrase in $script:BadPhrasesList) {
        if ($cleanText -match $phrase) { return $true }
    }

    return $false
}

function Test-ContainsLinkOrSpam {
    param([hashtable]$Msg, [string]$Text)

    if (-not [string]::IsNullOrWhiteSpace($Text)) {
        if ($Text -match '(?i)\bhttps?://|\bt\.me/|\btelegram\.me/|\bwww\.|@[a-zA-Z0-9_]{4,}') {
            return $true
        }
    }

    if ($Msg.ContainsKey("entities") -and $null -ne $Msg["entities"]) {
        foreach ($e in $Msg["entities"]) {
            $type = [string]$e["type"]
            if ($type -eq "url" -or $type -eq "text_link" -or $type -eq "mention") {
                return $true
            }
        }
    }

    if ($Msg.ContainsKey("caption_entities") -and $null -ne $Msg["caption_entities"]) {
        foreach ($e in $Msg["caption_entities"]) {
            $type = [string]$e["type"]
            if ($type -eq "url" -or $type -eq "text_link" -or $type -eq "mention") {
                return $true
            }
        }
    }

    if ($Msg.ContainsKey("reply_markup")) {
        return $true
    }

    if ($Msg.ContainsKey("forward_date") -or $Msg.ContainsKey("forward_from") -or $Msg.ContainsKey("forward_from_chat") -or $Msg.ContainsKey("forward_sender_name")) {
        return $true
    }

    return $false
}

function Test-IsNsfwSticker {
    param([hashtable]$Sticker)
    if ($null -eq $Sticker) { return $false }
    $setName = ""
    if ($Sticker.ContainsKey("set_name") -and $null -ne $Sticker["set_name"]) {
        $setName = [string]$Sticker["set_name"].ToLowerInvariant()
    }
    
    $nsfwKw = @("sex", "porn", "xxx", "nude", "naked", "nsfw", "18+", "18plus", "adult", "erotic", "hentai", "boobs", "dick", "pussy", "tits", "vagina", "brazzers", "onlyfans", "xvideo", "ass", "milf", "blowjob", "fuck", "horny", "bitch", "سێکس", "پۆرن", "قن", "قوز", "کیر", "حیز", "گواو", "سۆزانی")
    foreach ($kw in $nsfwKw) {
        if ($setName -match [regex]::Escape($kw)) { return $true }
    }
    return $false
}

function Test-IsNsfwAnimation {
    param([hashtable]$Msg, [string]$Text)
    if (Test-ContainsBadWord $Text) { return $true }
    $doc = $null
    if ($Msg.ContainsKey("animation")) { $doc = $Msg["animation"] }
    elseif ($Msg.ContainsKey("document")) { $doc = $Msg["document"] }
    
    if ($null -ne $doc -and $doc.ContainsKey("file_name")) {
        $fn = [string]$doc["file_name"].ToLowerInvariant()
        $nsfwKw = @("sex", "porn", "xxx", "nude", "naked", "nsfw", "18+", "adult", "erotic", "hentai", "boobs", "dick", "pussy", "tits", "vagina", "سێکس", "پۆرن")
        foreach ($kw in $nsfwKw) {
            if ($fn -match [regex]::Escape($kw)) { return $true }
        }
    }
    return $false
}

# ═══════════════════════════════════════════════════════════════════════════════
#  بەشی ٦: فرمانەکانی بەڕێوەبەر و ئەندامان
# ═══════════════════════════════════════════════════════════════════════════════

function Get-ReplyTargetUser {
    param([hashtable]$Message)
    if (-not $Message.ContainsKey("reply_to_message")) { return $null }
    if (-not $Message["reply_to_message"].ContainsKey("from")) { return $null }
    return $Message["reply_to_message"]["from"]
}

function ConvertTo-Minutes {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) { return 60 }
    if ($Value -match '^(\d+)(m|h|d)?$') {
        $n = [int]$Matches[1]; $u = $Matches[2]
        switch ($u) { 'h' { return $n * 60 }; 'd' { return $n * 1440 }; default { return $n } }
    }
    return 60
}

function Invoke-BotCommand {
    param([hashtable]$Message, [string]$Text)
    $chatId = [Int64]$Message["chat"]["id"]
    $msgId = [int]$Message["message_id"]
    $from = $Message["from"]
    $userId = [Int64]$from["id"]
    $name = Get-DisplayName $from
    $parts = $Text.Trim().Split(" ", 2, [System.StringSplitOptions]::RemoveEmptyEntries)
    $cmd = $parts[0].Split("@")[0].ToLowerInvariant()
    $arg = ""; if ($parts.Count -gt 1) { $arg = $parts[1] }

    switch ($cmd) {
        "/start" { 
            Send-TgMessage $chatId "🌸 سڵاو $name گیان! من بوتی گاردنیام 🤖`n`nخزمەتکاری گروپەکەتانم بۆ بەخێرهاتن، پاراستنی ئاسایش، و وەڵامدانەوەی پرسیارەکان بە کوردی!" $msgId 
        }
        "/help" { 
            $h = "📋 **فرمانەکانی بوتی گاردنیا:**`n`n" +
                 "• `/rules` - پیشاندانی یاساکان`n" +
                 "• `/id` - پیشاندانی ئایدی چات`n`n" +
                 "🛡️ **فرمانەکانی ئەدمین:**`n" +
                 "• `/warn` - ئاگاداری دان بە بەکارهێنەر`n" +
                 "• `/warnings` - ژمارەی ئاگادارییەکان`n" +
                 "• `/clearwarnings` - سڕینەوەی ئاگادارییەکان`n" +
                 "• `/mute 10m` - بێدەنگکردن`n" +
                 "• `/unmute` - لادانی بێدەنگی`n" +
                 "• `/ban` - باندکردن`n" +
                 "• `/unban <user_id>` - ئازادکردن`n" +
                 "• `/setrules <دەق>` - دانانی یاسا"
            Send-TgMessage $chatId $h $msgId 
        }
        "/id" { 
            Send-TgMessage $chatId "🆔 ئایدی چات: $chatId" $msgId 
        }
        "/rules" {
            $cKey = [string]$chatId
            if ($script:State["rules"].ContainsKey($cKey)) {
                Send-TgMessage $chatId "📜 **یاساکانی گروپ:**`n`n$($script:State["rules"][$cKey])" $msgId
            } else {
                Send-TgMessage $chatId "ℹ️ یاسایەک بۆ ئەم گروپە دانەنراوە." $msgId
            }
        }
        "/setrules" {
            if (-not (Test-IsAdmin $chatId $userId)) { Send-TgMessage $chatId "⚠️ تەنها ئەدمین دەتوانێت یاساکان دابنێت!" $msgId; return }
            if ([string]::IsNullOrWhiteSpace($arg)) { Send-TgMessage $chatId "تکایە دەقی یاساکان بنووسە: /setrules دەق..." $msgId; return }
            $script:State["rules"][[string]$chatId] = $arg
            Save-State
            Send-TgMessage $chatId "✅ یاساکانی گروپ نوێکرانەوە!" $msgId
        }
        "/warn" {
            if (-not (Test-IsAdmin $chatId $userId)) { Send-TgMessage $chatId "⚠️ تەنها ئەدمین دەتوانێت ئەم فرمانە بەکاربهێنێت!" $msgId; return }
            $t = Get-ReplyTargetUser $Message
            if ($null -eq $t) { Send-TgMessage $chatId "تکایە ڕیپلای پەیامی بەکارهێنەرەکە بکە!" $msgId; return }
            $cnt = Add-UserWarning $chatId ([Int64]$t["id"])
            Send-TgMessage $chatId "$(Get-DisplayName $t) ئاگادار کرایەوە! ⚠️ ($cnt/$($script:Config.maxWarnings))" $msgId
            if ($cnt -ge [int]$script:Config.maxWarnings) {
                Set-UserMute $chatId ([Int64]$t["id"]) [int]$script:Config.autoMuteMinutes
                Send-TgMessage $chatId "🚫 $(Get-DisplayName $t) بەهۆی دووبارەکردنەوەی سەرپێچی، بۆ ماوەی $($script:Config.autoMuteMinutes) خولەک لە چاتکردن بێدەنگ کرا!" $msgId
            }
        }
        "/warnings" {
            $t = Get-ReplyTargetUser $Message
            if ($null -eq $t) { Send-TgMessage $chatId "تکایە ڕیپلای پەیامی بەکارهێنەرەکە بکە!" $msgId; return }
            $cKey = [string]$chatId; $uKey = [string]$t["id"]
            $cnt = 0
            if ($script:State["warnings"].ContainsKey($cKey) -and $script:State["warnings"][$cKey].ContainsKey($uKey)) {
                $cnt = [int]$script:State["warnings"][$cKey][$uKey]
            }
            Send-TgMessage $chatId "📊 ژمارەی ئاگادارییەکانی $(Get-DisplayName $t): ($cnt/$($script:Config.maxWarnings))" $msgId
        }
        "/clearwarnings" {
            if (-not (Test-IsAdmin $chatId $userId)) { Send-TgMessage $chatId "⚠️ تەنها ئەدمین دەتوانێت ئەم فرمانە بەکاربهێنێت!" $msgId; return }
            $t = Get-ReplyTargetUser $Message
            if ($null -eq $t) { Send-TgMessage $chatId "تکایە ڕیپلای بکە" $msgId; return }
            Reset-UserWarnings $chatId ([Int64]$t["id"])
            Send-TgMessage $chatId "✅ ئاگادارییەکانی $(Get-DisplayName $t) سڕانەوە" $msgId
        }
        "/mute" {
            if (-not (Test-IsAdmin $chatId $userId)) { Send-TgMessage $chatId "⚠️ تەنها ئەدمین دەتوانێت ئەم فرمانە بەکاربهێنێت!" $msgId; return }
            $t = Get-ReplyTargetUser $Message
            if ($null -eq $t) { Send-TgMessage $chatId "تکایە ڕیپلای پەیامی بەکارهێنەرەکە بکە!" $msgId; return }
            $min = ConvertTo-Minutes $arg
            Set-UserMute $chatId ([Int64]$t["id"]) $min
            Send-TgMessage $chatId "🚫 $(Get-DisplayName $t) بۆ $min خولەک بێدەنگ کرا" $msgId
        }
        "/unmute" {
            if (-not (Test-IsAdmin $chatId $userId)) { Send-TgMessage $chatId "⚠️ تەنها ئەدمین دەتوانێت ئەم فرمانە بەکاربهێنێت!" $msgId; return }
            $t = Get-ReplyTargetUser $Message
            if ($null -eq $t) { Send-TgMessage $chatId "تکایە ڕیپلای بکە" $msgId; return }
            Set-UserUnmute $chatId ([Int64]$t["id"])
            Send-TgMessage $chatId "🔊 بێدەنگی لەسەر $(Get-DisplayName $t) لادرا" $msgId
        }
        "/ban" {
            if (-not (Test-IsAdmin $chatId $userId)) { Send-TgMessage $chatId "⚠️ تەنها ئەدمین دەتوانێت ئەم فرمانە بەکاربهێنێت!" $msgId; return }
            $t = Get-ReplyTargetUser $Message
            if ($null -eq $t) { Send-TgMessage $chatId "تکایە ڕیپلای بکە" $msgId; return }
            Remove-UserFromChat $chatId ([Int64]$t["id"])
            Send-TgMessage $chatId "🚫 $(Get-DisplayName $t) لە گروپەکە دەرکرا و باند کرا" $msgId
        }
        "/unban" {
            if (-not (Test-IsAdmin $chatId $userId)) { Send-TgMessage $chatId "⚠️ تەنها ئەدمین دەتوانێت ئەم فرمانە بەکاربهێنێت!" $msgId; return }
            if ($arg -notmatch '^\d+$') { Send-TgMessage $chatId "نمونە: /unban 123456789" $msgId; return }
            Restore-UserToChat $chatId ([Int64]$arg)
            Send-TgMessage $chatId "✅ ئایدی $arg ئازاد کرایەوە" $msgId
        }
    }
}

# ═══════════════════════════════════════════════════════════════════════════════
#  بەشی ٧: پشکنینی پەیامەکان (Message Processor)
# ═══════════════════════════════════════════════════════════════════════════════

function Invoke-HandleMessage {
    param([hashtable]$Message)
    if (-not $Message.ContainsKey("chat") -or -not $Message.ContainsKey("from")) { return }
    $chat = $Message["chat"]
    $chatType = $chat["type"]
    if ($chatType -ne "group" -and $chatType -ne "supergroup" -and $chatType -ne "private") { return }
    $chatId = [Int64]$chat["id"]
    $msgId = [int]$Message["message_id"]
    $from = $Message["from"]
    $userId = [Int64]$from["id"]
    $displayName = Get-DisplayName $from

    # ── 🌸 ١. بەخێرهاتنی ئەندامانی نوێ ──
    if ($Message.ContainsKey("new_chat_members")) {
        foreach ($member in $Message["new_chat_members"]) {
            if ($member.ContainsKey("is_bot") -and $member["is_bot"]) { continue }
            $mName = Get-DisplayName $member
            $wMsg = (Get-RandomItem $script:WelcomeMessages).Replace("{name}", $mName)
            Send-TgMessage $chatId $wMsg $msgId
        }
    }

    # ── دەق ──
    $text = ""
    if ($Message.ContainsKey("text")) { $text = [string]$Message["text"] }
    elseif ($Message.ContainsKey("caption")) { $text = [string]$Message["caption"] }

    # ── فرمان ──
    if ($text.StartsWith("/")) {
        Invoke-BotCommand $Message $text
        return
    }

    # ── چاتی تایبەت ──
    if ($chatType -eq "private") {
        if ([bool]$script:Config.aiInPrivateChats -and -not [string]::IsNullOrWhiteSpace($text)) {
            $reply = Get-AIReply $chatId $userId $text
            if (-not [string]::IsNullOrWhiteSpace($reply)) { Send-TgMessage $chatId $reply $msgId }
        }
        return
    }

    # ══════ 🛡️ ۲. ئاسایشی گروپ بۆ نائەدمینەکان ══════
    $isAdmin = Test-IsAdmin $chatId $userId

    if (-not $isAdmin) {
        $violationReason = ""

        if ([bool]$script:Config.blockPhotos -and $Message.ContainsKey("photo")) {
            $violationReason = "ناردنی وێنە 📷"
        }
        elseif ([bool]$script:Config.blockVideos -and ($Message.ContainsKey("video") -or $Message.ContainsKey("video_note"))) {
            $violationReason = "ناردنی ڤیدیۆ 🎥"
        }
        elseif ($Message.ContainsKey("sticker") -and (Test-IsNsfwSticker $Message["sticker"])) {
            $violationReason = "ناردنی ستیکەری نەشیاو و سێکسی 🔞"
        }
        elseif ([bool]$script:Config.blockAllStickers -and $Message.ContainsKey("sticker")) {
            $violationReason = "ناردنی ستیکەر 🎭"
        }
        elseif (($Message.ContainsKey("animation") -or $Message.ContainsKey("document")) -and (Test-IsNsfwAnimation $Message $text)) {
            $violationReason = "ناردنی گیف یان فایلی نەشیاو 🔞"
        }
        elseif ([bool]$script:Config.blockAllGIFs -and ($Message.ContainsKey("animation") -or $Message.ContainsKey("document"))) {
            $violationReason = "ناردنی GIF / فۆرمات / فایل 🎬"
        }
        elseif ($Message.ContainsKey("voice") -or $Message.ContainsKey("audio")) {
            if ([bool]$script:Config.blockVoice) {
                $violationReason = "ناردنی فایلی دەنگی 🎙️"
            }
        }
        elseif ([bool]$script:Config.blockLinks -and (Test-ContainsLinkOrSpam $Message $text)) {
            $violationReason = "ناردنی لینک، پۆست یان ریپڵای دوگمەدار 🔗"
        }
        elseif ([bool]$script:Config.blockBadWords -and (Test-ContainsBadWord $text)) {
            $violationReason = "قسەی ناشرین و جنێو 🤬"
        }

        if (-not [string]::IsNullOrWhiteSpace($violationReason)) {
            Remove-TgMessage $chatId $msgId
            $cnt = Add-UserWarning $chatId $userId
            Send-TgMessage $chatId "⚠️ $displayName $violationReason قەدەغەیە! ئاگاداری: ($cnt/$($script:Config.maxWarnings))"
            
            if ($cnt -ge [int]$script:Config.maxWarnings) {
                Set-UserMute $chatId $userId [int]$script:Config.autoMuteMinutes
                Send-TgMessage $chatId "🚫 $displayName بەهۆی دووبارەکردنەوەی سەرپێچی، بۆ ماوەی $($script:Config.autoMuteMinutes) خولەک لە چاتکردن بێدەنگ کرا!"
            }
            return
        }
    }

    # ── 💬 ۳. وەڵامدانەوەی AI ──
    if (-not [string]::IsNullOrWhiteSpace($text)) {
        $shouldAiReply = $true

        if ($Message.ContainsKey("reply_to_message") -and $null -ne $Message["reply_to_message"]) {
            $repTarget = $Message["reply_to_message"]
            if ($repTarget.ContainsKey("from") -and $null -ne $repTarget["from"]) {
                $targetUser = $repTarget["from"]
                $targetId = [Int64]$targetUser["id"]
                $isTargetBot = [bool]($targetUser.ContainsKey("is_bot") -and $targetUser["is_bot"])

                if ($targetId -ne $script:BotId -and -not $isTargetBot) {
                    $shouldAiReply = $false
                }
            }
        }

        if ($shouldAiReply) {
            $reply = Get-AIReply $chatId $userId $text
            if (-not [string]::IsNullOrWhiteSpace($reply)) {
                Send-TgMessage $chatId $reply $msgId
            }
        }
    }
}

# ═══════════════════════════════════════════════════════════════════════════════
#  بەشی ٨: دەستپێکردن و لووپی چاودێری
# ═══════════════════════════════════════════════════════════════════════════════

Invoke-Telegram "deleteWebhook" @{ drop_pending_updates = $true } | Out-Null

$script:State["aiHistory"] = @{}
Save-State

Write-Host "===============================================" -ForegroundColor Cyan
Write-Host "  Gardnya Security & AI Protection Bot Started!" -ForegroundColor Green
Write-Host "  AI Model: $($Config.groqModel)" -ForegroundColor Yellow
Write-Host "  All Security & Anti-Spam Protections Active" -ForegroundColor Yellow
Write-Host "===============================================" -ForegroundColor Cyan
Write-Host "  Ctrl+C to stop" -ForegroundColor DarkGray
Write-Host ""

$offset = 0
while ($true) {
    try {
        $response = Invoke-Telegram "getUpdates" @{ offset = $offset; timeout = 30; allowed_updates = @("message") }
        if ($null -eq $response -or -not $response.ok) { Start-Sleep -Seconds 3; continue }
        foreach ($update in $response.result) {
            $updateHash = ConvertTo-Hashtable $update
            $offset = [int]$updateHash["update_id"] + 1
            if ($updateHash.ContainsKey("message")) {
                try { Invoke-HandleMessage $updateHash["message"] }
                catch { Write-Warning "Error: $($_.Exception.Message)" }
            }
        }
    } catch {
        Write-Warning "Loop: $($_.Exception.Message)"
        Start-Sleep -Seconds 5
    }
}
