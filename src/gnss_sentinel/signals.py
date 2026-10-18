"""Offline signal fixtures and deterministic DSP. Never transmits RF."""
import numpy as np
from scipy.signal import ShortTimeFFT, windows

SIGNAL_CLASSES = ["clean", "narrowband", "chirp", "pulsed", "am", "fm"]
IQ_FEATURES = ["power_db", "crest_factor", "spectral_entropy", "spectral_flatness",
               "peak_fraction", "occupied_bandwidth", "envelope_cv", "phase_step_std",
               "duty_cycle", "spectral_centroid", "spectral_spread", "envelope_kurtosis"]


def validate_iq(iq, sample_rate):
    x = np.asarray(iq, dtype=np.complex128)
    if x.ndim != 1 or not 256 <= len(x) <= 131072:
        raise ValueError("IQ input must contain 256–131072 complex samples.")
    if not np.isfinite(x).all() or np.max(np.abs(x)) > 1e10:
        raise ValueError("IQ samples must be finite with magnitude at most 1e10.")
    if not np.isfinite(sample_rate) or not 1000 <= sample_rate <= 100_000_000:
        raise ValueError("Sample rate must be 1 kHz–100 MHz.")
    if np.max(np.abs(x)) < 1e-12:
        raise ValueError("A zero-energy recording cannot be analyzed.")
    return x


def synthesize(kind="chirp", snr_db=10, seed=42, samples=4096, sample_rate=2_000_000):
    if kind not in SIGNAL_CLASSES:
        raise ValueError("Unsupported signal class.")
    rng = np.random.default_rng(seed)
    t = np.arange(samples) / sample_rate
    noise = (rng.normal(size=samples) + 1j * rng.normal(size=samples)) / np.sqrt(2)
    f = rng.uniform(.04, .28) * sample_rate
    phase = rng.uniform(0, 2 * np.pi)
    carrier = np.exp(1j * (2 * np.pi * f * t + phase))
    if kind == "clean":
        return noise
    if kind == "narrowband":
        signal = carrier
    elif kind == "chirp":
        sweep = rng.uniform(.15, .7) * sample_rate / max(t[-1], 1e-9)
        signal = np.exp(1j * (2 * np.pi * (-f * t + .5 * sweep * t**2) + phase))
    elif kind == "pulsed":
        period = rng.integers(100, 450)
        gate = (np.arange(samples) % period) < period * rng.uniform(.08, .25)
        signal = carrier * gate
    elif kind == "am":
        signal = carrier * (1 + .9 * np.cos(2 * np.pi * sample_rate * .008 * t))
    else:
        signal = np.exp(1j * (2 * np.pi * f * t + rng.uniform(2, 6) * np.sin(2 * np.pi * sample_rate * .01 * t)))
    signal /= np.sqrt(np.mean(np.abs(signal)**2) + 1e-12)
    return noise + 10**(snr_db / 20) * signal


def features(iq, sample_rate=2_000_000):
    x = validate_iq(iq, sample_rate)
    amplitude = np.abs(x)
    power = np.abs(np.fft.fftshift(np.fft.fft(x * np.hanning(len(x)))))**2 + 1e-20
    p = power / power.sum()
    f = np.linspace(-.5, .5, len(x), endpoint=False)
    centroid = np.sum(f * p)
    cdf = np.cumsum(p)
    occupied = f[min(np.searchsorted(cdf, .99), len(f)-1)] - f[np.searchsorted(cdf, .01)]
    variance = np.var(amplitude) + 1e-12
    values = [10*np.log10(np.mean(amplitude**2) + 1e-20), amplitude.max() / (np.sqrt(np.mean(amplitude**2))+1e-12),
              -np.sum(p*np.log(p)) / np.log(len(p)), np.exp(np.mean(np.log(power))) / power.mean(),
              p.max(), occupied, amplitude.std()/(amplitude.mean()+1e-12),
              np.std(np.angle(x[1:]*np.conj(x[:-1]))), np.mean(amplitude > amplitude.max()*.5),
              centroid, np.sqrt(np.sum((f-centroid)**2*p)), np.mean((amplitude-amplitude.mean())**4)/variance**2]
    return dict(zip(IQ_FEATURES, map(float, values)))


def analyze(iq, sample_rate=2_000_000):
    x = validate_iq(iq, sample_rate)
    # Bound visualization cost independently of accepted recording length.
    segment = x[:16384]
    transform = ShortTimeFFT(windows.hann(256, sym=False), hop=128, fs=sample_rate, fft_mode="centered")
    spec = np.abs(transform.stft(segment))**2
    db = 10*np.log10(spec + 1e-12)
    spectrum = 10*np.log10(np.mean(spec, axis=1) + 1e-12)
    times = transform.t(len(segment))
    return {"features": features(x, sample_rate), "sample_count": len(x), "sample_rate": sample_rate,
            "duration_ms": len(x)/sample_rate*1000, "frequency_khz": (transform.f/1000).tolist(),
            "spectrum_db": spectrum.tolist(), "spectrogram_db": db.T.tolist(),
            "time_ms": (times*1000).tolist(), "display_samples": len(segment),
            "waveform": {"i": x[:256].real.tolist(), "q": x[:256].imag.tolist()}}
