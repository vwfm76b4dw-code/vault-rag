#include<bits/stdc++.h>
using namespace std;
int ans = 0;
int maze[66][66];
int used[66][66];
int fx[4][2] = {{-1,0},{1,0},{0,-1},{0,1}};
int n,m;
int s1,s2;
int s3,s4;
int t;
void dfs(int x,int y){
	if(x == s3 && y == s4){
		ans++;
		return;
	} else {
		used[x][y] = 1;
		for(int i = 0;i < 4;i++){
			int nx = x + fx[i][0];
			int ny = y + fx[i][1];
			if(nx >= 1 && nx <= n && ny >= 1 && ny <= m && used[nx][ny] == 0 && maze[nx][ny] == 0){
				used[nx][ny] = 1;
				dfs(nx,ny);
				used[nx][ny] = 0;
			}
		}
		used[x][y] = 0;
	}
}
int main()
{
	cin>>n>>m>>t;
	cin>>s1>>s2;
	cin>>s3>>s4;
	for(int i = 0;i < t;i++){
		int x,y;
		cin >>x >> y;
		maze[x][y] = 1;
	}
	dfs(s1,s2);
	cout << ans;
}
