// keychain-gate <service> <account> <reason>: a Keychain password, released only after the person approves.
//
// The approval is macOS's own: Apple Watch, Touch ID or the login password, whichever the Mac offers. Entries
// stored with `-T <this binary>` trust only it, so nothing else reads them without the classic password prompt,
// and this reads them only after an approval. An empty account matches the service's first entry.
//
// Exit 0 with the password on stdout; 1 not approved; 2 no such entry; 3 usage.
//
// keychain-gate --adopt <service> <account>: store an existing entry again so it trusts only this binary,
// without anyone retyping the secret. Reading the old entry shows its classic prompt one last time. A backup
// copy is kept until the new entry is saved, so a failure can't lose the secret. Exit 0 done, 2 no such entry,
// 1 the old entry's read wasn't allowed (its prompt denied or cancelled), 4 the Keychain refused (the message
// says where the backup is).
import Foundation
import LocalAuthentication
import Security

let args = CommandLine.arguments

func entryQuery(_ service: String, _ account: String) -> [String: Any] {
    var query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service]
    if !account.isEmpty {
        query[kSecAttrAccount as String] = account
    }
    return query
}

func add(_ service: String, _ account: String, _ label: String, _ secret: Data) -> OSStatus {
    var me: SecTrustedApplication?
    var access: SecAccess?
    guard SecTrustedApplicationCreateFromPath(nil, &me) == errSecSuccess, let me = me,
          SecAccessCreate(label as CFString, [me] as CFArray, &access) == errSecSuccess, let access = access else {
        return errSecInternalComponent
    }
    var item = entryQuery(service, account)
    item[kSecAttrLabel as String] = label
    item[kSecValueData as String] = secret
    item[kSecAttrAccess as String] = access
    return SecItemAdd(item as CFDictionary, nil)
}

func fail(_ message: String, _ code: Int32) -> Never {
    FileHandle.standardError.write(Data((message + "\n").utf8))
    exit(code)
}

if args.count == 4 && args[1] == "--adopt" {
    let (service, wanted) = (args[2], args[3])
    var query = entryQuery(service, wanted)
    query[kSecMatchLimit as String] = kSecMatchLimitOne
    query[kSecReturnAttributes as String] = true
    query[kSecReturnData as String] = true
    var found: CFTypeRef?
    let read = SecItemCopyMatching(query as CFDictionary, &found)
    if read == errSecItemNotFound {
        exit(2)
    }
    guard read == errSecSuccess, let old = found as? [String: Any], let secret = old[kSecValueData as String] as? Data
    else { fail("the old entry's read wasn't allowed (\(read)); nothing changed", 1) }
    let account = old[kSecAttrAccount as String] as? String ?? wanted
    let label = old[kSecAttrLabel as String] as? String ?? service
    let backup = service + ".taxtrace-backup"
    SecItemDelete(entryQuery(backup, account) as CFDictionary)
    var status = add(backup, account, label, secret)
    guard status == errSecSuccess else { fail("couldn't save a backup copy (\(status)); nothing changed", 4) }
    status = SecItemDelete(entryQuery(service, account) as CFDictionary)
    guard status == errSecSuccess else { fail("couldn't remove the old entry (\(status)); nothing changed", 4) }
    status = add(service, account, label, secret)
    guard status == errSecSuccess else { fail("couldn't save the new entry (\(status)); the secret is in \(backup)", 4) }
    SecItemDelete(entryQuery(backup, account) as CFDictionary)
    exit(0)
}

guard args.count == 4 else {
    FileHandle.standardError.write(Data("usage: keychain-gate <service> <account> <reason>\n".utf8))
    exit(3)
}
let (service, account, reason) = (args[1], args[2], args[3])

var query = entryQuery(service, account)
query[kSecMatchLimit as String] = kSecMatchLimitOne
query[kSecReturnAttributes as String] = true  // attributes only: no password is read, so nothing is asked yet
var found: CFTypeRef?
if SecItemCopyMatching(query as CFDictionary, &found) != errSecSuccess {
    exit(2)  // a missing entry costs no approval
}

let context = LAContext()
var policy = LAPolicy.deviceOwnerAuthenticationWithBiometricsOrCompanion  // Touch ID or a paired Apple Watch
var unavailable: NSError?
if !context.canEvaluatePolicy(policy, error: &unavailable) {
    policy = .deviceOwnerAuthentication  // neither set up: the login password
}
let done = DispatchSemaphore(value: 0)
var approved = false
context.evaluatePolicy(policy, localizedReason: reason) { ok, _ in
    approved = ok
    done.signal()
}
done.wait()
guard approved else { exit(1) }

query.removeValue(forKey: kSecReturnAttributes as String)
query[kSecReturnData as String] = true
var data: CFTypeRef?
guard SecItemCopyMatching(query as CFDictionary, &data) == errSecSuccess,
      let bytes = data as? Data, let secret = String(data: bytes, encoding: .utf8) else {
    exit(2)
}
FileHandle.standardOutput.write(Data(secret.utf8))
