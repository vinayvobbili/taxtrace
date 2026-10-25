// approval_check [--try]: which ways macOS offers to approve a read, as keychain-gate would ask, without a
// Keychain entry or a secret anywhere near it.
//
// Each policy's line says whether it can be evaluated now and, if not, LocalAuthentication's error code. With
// --try, the Touch ID / Apple Watch policy is evaluated once (the person sees the prompt) and the outcome printed:
// what keychain-gate gets back before it would fall back to the password.
import Foundation
import LocalAuthentication

let names: [Int: String] = [
    LAError.authenticationFailed.rawValue: "authenticationFailed", LAError.userCancel.rawValue: "userCancel",
    LAError.userFallback.rawValue: "userFallback", LAError.systemCancel.rawValue: "systemCancel",
    LAError.passcodeNotSet.rawValue: "passcodeNotSet", LAError.biometryNotAvailable.rawValue: "biometryNotAvailable",
    LAError.biometryNotEnrolled.rawValue: "biometryNotEnrolled", LAError.biometryLockout.rawValue: "biometryLockout",
    LAError.appCancel.rawValue: "appCancel", LAError.invalidContext.rawValue: "invalidContext",
    LAError.notInteractive.rawValue: "notInteractive", LAError.companionNotAvailable.rawValue: "companionNotAvailable",
    LAError.biometryNotPaired.rawValue: "biometryNotPaired", LAError.biometryDisconnected.rawValue: "biometryDisconnected",
    LAError.invalidDimensions.rawValue: "invalidDimensions",
]

func describe(_ error: Error?) -> String {
    guard let error = error as NSError? else { return "" }
    return names[error.code].map { "\($0) (\(error.code))" } ?? "\(error.domain) \(error.code)"
}

let policies: [(String, LAPolicy)] = [
    ("Touch ID or Apple Watch", .deviceOwnerAuthenticationWithBiometricsOrCompanion),
    ("Touch ID", .deviceOwnerAuthenticationWithBiometrics),
    ("Apple Watch", .deviceOwnerAuthenticationWithCompanion),
    ("any (password last)", .deviceOwnerAuthentication),
]
for (name, policy) in policies {
    var error: NSError?
    let ok = LAContext().canEvaluatePolicy(policy, error: &error)
    print("\(name): " + (ok ? "available" : "not available, \(describe(error))"))
}
let context = LAContext()
var none: NSError?
_ = context.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: &none)
print("biometry: \(context.biometryType == .touchID ? "Touch ID" : context.biometryType == .none ? "none" : "other")")

if CommandLine.arguments.contains("--try") {
    let done = DispatchSemaphore(value: 0)
    var outcome = ""
    LAContext().evaluatePolicy(.deviceOwnerAuthenticationWithBiometricsOrCompanion,
                               localizedReason: "check how taxtrace's Keychain reads are approved") { ok, error in
        outcome = ok ? "approved" : "not approved, \(describe(error))"
        done.signal()
    }
    done.wait()
    print("try (Touch ID or Apple Watch): \(outcome)")
}
