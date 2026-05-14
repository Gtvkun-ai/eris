using Godot;
using System;
using System.Collections.Generic;

//Class này không cho kế thừa
public sealed class BodyAudioController
{
	//Tạo một AudioStreamPlayer để phát âm thanh
	private readonly AudioStreamPlayer _player = new();
	//Dùng để chọn ngẫu nhiên một âm thanh trong danh sách
	private readonly Random _rng = new();
	//Đây là hàm lấy animation/action hiện tại
	private Func<string> _currentActionProvider = () => "stand";

	//Danh sách animation được phép lặp âm thanh sau khi sound hiện tại phát xong
	private static readonly HashSet<string> LoopingSoundAnimations = new()
	{
		"stand_walk", "sleep", "hop", "climb",
	};

	private static readonly Dictionary<string, string[]> SoundMap = new()
	//animation name -> danh sách file sound
	{
		{ "affection",   new[] { "res://asset/Monika/sound/Cuddling.wav", "res://asset/Monika/sound/Giggle.wav", "res://asset/Monika/sound/Happy_Squeals.wav", "res://asset/Monika/sound/Squeal_Happy.wav" } },
		{ "air",         new[] { "res://asset/Monika/sound/Cartoon_Aah.wav", "res://asset/Monika/sound/Cartoon_Jump2.wav" } },
		{ "stand_walk",  new[] { "res://asset/Monika/sound/Cute_Run.wav", "res://asset/Monika/sound/Cartoon_Hop.wav" } },
		{ "sad",         new[] { "res://asset/Monika/sound/Hurt_Aah.wav", "res://asset/Monika/sound/Hurt_Unh.wav", "res://asset/Monika/sound/Sigh_Sleepy.wav" } },
		{ "read",        new[] { "res://asset/Monika/sound/Nyaa_Soft.wav" } },
		{ "piano",       new[] { "res://asset/Monika/sound/Giggle_Short.wav", "res://asset/Monika/sound/Giggle.wav" } },
		{ "food",        new[] { "res://asset/Monika/sound/Cartoon_Plop.wav", "res://asset/Monika/sound/Cartoon_Pop.wav" } },
		{ "clone",       new[] { "res://asset/Monika/sound/Cartoon_Pop.wav", "res://asset/Monika/sound/Happy_Squeals.wav" } },
		{ "divine",      new[] { "res://asset/Monika/sound/Cartoon_Pop.wav", "res://asset/Monika/sound/Happy_Squeals.wav" } },
		{ "stand",       new[] { "res://asset/Monika/sound/Nyaa_Quick.wav", "res://asset/Monika/sound/Nyaa_Soft.wav" } },
		{ "sit_down",    new[] { "res://asset/Monika/sound/Cartoon_Plop.wav" } },
		{ "sit_up",      new[] { "res://asset/Monika/sound/Cartoon_Plop.wav", "res://asset/Monika/sound/Nyaa_Quick.wav" } },
		{ "sit",         new[] { "res://asset/Monika/sound/Cartoon_Plop.wav", "res://asset/Monika/sound/Nyaa_Soft.wav" } },
		{ "climb",       new[] { "res://asset/Monika/sound/Cute_Run.wav" } },
		{ "climb_top",   new[] { "res://asset/Monika/sound/Cute_Run.wav", "res://asset/Monika/sound/Cartoon_Impact_F.wav" } },
		{ "hop",         new[] { "res://asset/Monika/sound/Cartoon_Hop.wav", "res://asset/Monika/sound/Cartoon_Jump2.wav" } },
		{ "jump",        new[] { "res://asset/Monika/sound/Cartoon_Jump2.wav", "res://asset/Monika/sound/Cartoon_Aah.wav" } },
		{ "sleep",       new[] { "res://asset/Monika/sound/Sigh_Sleepy.wav", "res://asset/Monika/sound/Cuddling.wav" } },
		{ "air_swing_l", new[] { "res://asset/Monika/sound/Cartoon_Aah.wav", "res://asset/Monika/sound/Squeal_Happy.wav" } },
		{ "air_swing_r", new[] { "res://asset/Monika/sound/Cartoon_Aah.wav", "res://asset/Monika/sound/Squeal_Happy.wav" } },
	};

	//Hàm này dùng để gắn controller vào một node trong scene
	public void Attach(Node owner, Func<string> currentActionProvider)
	{
		_currentActionProvider = currentActionProvider ?? _currentActionProvider; //Nếu truyền vào hàm lấy action hiện tại thì dùng nó. Nếu null thì giữ hàm cũ.
		owner.AddChild(_player); //Gắn _player vào cây scene của Godot
		_player.Finished += OnFinished; //Khi âm thanh phát xong, Godot gọi OnFinished
	}

	//Hàm phát sound tương ứng với animation.
	public void PlayForAnimation(string animation)
	{
		if (!SoundMap.TryGetValue(animation, out var sounds))
			return;

		//Random một file sound trong danh sách.
		string path = sounds[_rng.Next(sounds.Length)];
		var stream = GD.Load<AudioStream>(path);
		if (stream == null)
		{
			GD.PrintErr($"[Sound] Khong tai duoc: {path}");
			return;
		}

		//Gán stream vào player rồi phát.
		_player.Stream = stream;
		_player.Play();
	}

	private void OnFinished()
	{
		//Lấy action hiện tại. Nếu provider null thì fallback "stand".
		string currentAction = _currentActionProvider?.Invoke() ?? "stand";
		//Nếu action hiện tại thuộc nhóm được loop, phát tiếp âm thanh tương ứng.
		if (LoopingSoundAnimations.Contains(currentAction))
			PlayForAnimation(currentAction);
	}
}
